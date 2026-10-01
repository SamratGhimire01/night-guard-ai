"""Seeds backend/data/style_exemplars/seed_v1.csv into the style_exemplars table.

Run once after migration c2d3e4f5a6b7: docker exec night_guard_ai-backend-1
python scripts/seed_style_exemplars.py

CSV's business_type column conflates two concepts, mapped here: "shared" means
truly universal (StyleExemplar.business_type=None, matches every tenant
regardless of its own business_type), any other value (dental/trekking/
study_abroad/organic_food) means "shared across every tenant of that flavor"
(StyleExemplar.business_type=<that value>, business_id stays None). No row in
this seed set is a real single-tenant override (business_id set) -- the schema
supports that for later, this seed set doesn't use it.

Idempotent: skips a row whose (business_type, intent, language, text) already
exists, so a re-run after adding new rows to the CSV only inserts the new ones.

--prune also deletes every seeded (business_id IS NULL) row whose text is no longer in
the CSV -- needed after a CSV row is reworded (2026-10-01 natural-Nepali pass: the old
"नमस्ते है!" / "abhi thik garchu" / "sahayog" rows), since otherwise the old wording stays
in the table and keeps being retrieved. Tenant-specific rows (business_id set) are never
touched.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import SessionLocal
from app.db.models.style_exemplar import StyleExemplar
from app.services import style_exemplar_service

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "style_exemplars" / "seed_v1.csv"


def main(prune: bool = False) -> None:
    db = SessionLocal()
    try:
        existing = {
            (e.business_type, e.intent, e.language, e.text)
            for e in db.query(StyleExemplar).all()
        }
        rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
        created = 0
        skipped = 0
        for row in rows:
            business_type = None if row["business_type"] == "shared" else row["business_type"]
            key = (business_type, row["intent"], row["language"], row["text"])
            if key in existing:
                skipped += 1
                continue
            style_exemplar_service.create_exemplar(
                db,
                business_id=None,
                business_type=business_type,
                intent=row["intent"],
                language=row["language"],
                register=row["register"],
                text=row["text"],
            )
            existing.add(key)
            created += 1
        pruned = 0
        if prune:
            wanted = {
                (None if r["business_type"] == "shared" else r["business_type"], r["intent"], r["language"], r["text"])
                for r in rows
            }
            for e in db.query(StyleExemplar).filter(StyleExemplar.business_id.is_(None)).all():
                if (e.business_type, e.intent, e.language, e.text) not in wanted:
                    db.delete(e)
                    pruned += 1
            db.commit()
        print(
            f"style exemplar seed: {created} created, {skipped} already present, {pruned} retired, "
            f"{len(rows)} total in CSV"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main(prune="--prune" in sys.argv[1:])
