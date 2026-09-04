import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.appointment import Appointment, AppointmentStatus
from app.db.models.notification import Notification, NotificationStatus
from app.schemas.customer import CustomerUpdate
from app.services import customer_service
from app.services.conversation.tools import ConversationTool
from app.services.notifications import dispatch_notification

logger = logging.getLogger(__name__)


class UpdateContactInfoTool(ConversationTool):
    """The real write path for a customer volunteering their name/email/phone
    mid-conversation (e.g. an anonymous widget "Website Visitor" who never had
    an email on file). Same master-plan discipline as every tool since Phase
    10: the LLM only ever gets to extract candidate fields (see intent.py's
    `contact_info_update`) — this class is the only thing that actually calls
    `customer_service.update_customer` and, when applicable, triggers a real
    notification re-dispatch. The LLM never sees this run, only its result.

    NOT registered in `tools.TOOL_REGISTRY`: that dict is keyed one-tool-per-
    intent (find_tool(intent)), but contact info can be volunteered under ANY
    intent (mid-booking, mid-follow-up, etc.) — same reasoning as why
    handoff_service.maybe_create_handoff is also called directly by the
    orchestrator rather than through TOOL_REGISTRY. Still a real
    ConversationTool subclass (not a bespoke ad-hoc function) so it follows
    the exact same "only tool.run() mutates data" shape as every other tool.
    """

    name = "update_contact_info"
    handles_intents = frozenset()

    def run(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        customer_id: uuid.UUID,
        fields: dict,
        **kwargs,
    ) -> dict:
        """`fields` is already the diffed, changed-only subset the orchestrator
        computed against the real current Customer row (see
        orchestrator._resolve_contact_update) — never the LLM's raw claim
        about what's already on file."""
        try:
            payload = CustomerUpdate(**fields)
        except ValueError as exc:
            logger.info("update_contact_info rejected invalid fields=%s: %s", fields, exc)
            return {"success": False, "updated_fields": [], "customer": None, "resends": []}

        customer = customer_service.update_customer(
            db, business_id=business_id, customer_id=customer_id, payload=payload
        )
        if customer is None:
            return {"success": False, "updated_fields": [], "customer": None, "resends": []}

        logger.info(
            "update_contact_info tool executed: business_id=%s customer_id=%s fields=%s",
            business_id,
            customer_id,
            list(fields.keys()),
        )

        resends = []
        if "email" in fields or "phone" in fields:
            resends = self._resend_failed_notifications(db, business_id=business_id, customer=customer)

        return {
            "success": True,
            "updated_fields": list(fields.keys()),
            "customer": {
                "name": customer.name,
                "email": customer.email,
                "phone": customer.phone,
                "preferred_language": customer.preferred_language,
            },
            "resends": resends,
        }

    def _resend_failed_notifications(self, db: Session, *, business_id: uuid.UUID, customer) -> list[dict]:
        """Phase 13's real dispatch pipeline, re-run for real — never narrated.
        Scoped to this customer's currently-CONFIRMED appointments (a
        cancelled/completed appointment's stale notification isn't worth
        resending), and only notifications that genuinely FAILED before (a
        SENT/SIMULATED/DELIVERED one is left alone — never re-sent twice).
        Reuses the notification's existing channel rather than re-resolving
        it: the common real case this fixes is exactly "channel=email, no
        recipient on file yet" — see PHASE_STATUS.md for why a full
        channel-reresolution wasn't needed here.
        """
        confirmed_appointment_ids = db.execute(
            select(Appointment.id).where(
                Appointment.business_id == business_id,
                Appointment.customer_id == customer.id,
                Appointment.status == AppointmentStatus.CONFIRMED,
            )
        ).scalars().all()
        if not confirmed_appointment_ids:
            return []

        failed_notifications = db.execute(
            select(Notification).where(
                Notification.business_id == business_id,
                Notification.appointment_id.in_(confirmed_appointment_ids),
                Notification.status == NotificationStatus.FAILED,
            )
        ).scalars().all()

        results = []
        for notification in failed_notifications:
            dispatch_notification(db, notification)
            db.refresh(notification)
            results.append(
                {
                    "notification_id": str(notification.id),
                    "appointment_id": str(notification.appointment_id),
                    "channel": notification.channel,
                    "status": notification.status.value,
                }
            )
            logger.info(
                "update_contact_info triggered real re-dispatch: notification_id=%s new_status=%s",
                notification.id,
                notification.status.value,
            )
        return results
