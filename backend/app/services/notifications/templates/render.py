from pathlib import Path

from jinja2 import Environment, FileSystemLoader

# autoescape=True unconditionally: every template in this environment is HTML,
# and interpolated values (business name, customer name) are real user data —
# this is what prevents a business/customer name containing "<" or "&" from
# corrupting the email's markup, without hand-escaping every value by hand at
# every call site.
_env = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=True)


def render_appointment_email(**context) -> str:
    return _env.get_template("appointment.html.j2").render(**context)


def render_daily_report_email(**context) -> str:
    return _env.get_template("daily_report.html.j2").render(**context)


def render_monthly_report_email(**context) -> str:
    return _env.get_template("monthly_report.html.j2").render(**context)
