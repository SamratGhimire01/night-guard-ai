"""Sandbox businesses. Each is a small config shaped like the real dashboard's
per-business data (Business name/address/currency/languages, BusinessHours per
day, Service name/price/duration, free-text policies) and rendered to the same
kind of facts block the receptionist sees. All FICTIONAL -- no real business or
customer data. Add a business = add one dict here; nothing else is
business-specific anywhere in the lab."""

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

BUSINESSES: dict[str, dict] = {
    "dental": {
        "name": "Demo Dental Clinic", "type": "dental clinic", "address": "New Baneshwor, Kathmandu", "currency": "NPR",
        "hours": {d: ("9:00 AM", "6:00 PM") for d in _DAYS[:5]},
        "services": [("Teeth Cleaning", 1500, "30 min"), ("Tooth Filling", 2500, "45 min"), ("Root Canal", 9000, "90 min"),
                     ("Teeth Whitening", 6000, "45 min"), ("Dental Consultation", 500, "20 min")],
        "policies": ["cancel at least 4 hours before", "on-site parking available", "payment by cash, eSewa, or Khalti"],
    },
    "salon": {
        "name": "Demo Hair Salon", "type": "hair salon", "address": "Jawalakhel, Lalitpur", "currency": "NPR",
        "hours": {d: ("9:00 AM", "8:00 PM") for d in _DAYS},
        "services": [("Haircut", 600, "30 min"), ("Hair Colour", 3500, "120 min"), ("Facial", 1800, "60 min"),
                     ("Beard Trim", 300, "15 min")],
        "policies": ["walk-ins welcome if a stylist is free", "late by more than 15 minutes may lose the slot",
                     "payment by cash or eSewa"],
    },
    "trek": {
        "name": "Demo Himalayan Treks", "type": "trekking agency", "address": "Thamel, Kathmandu", "currency": "USD",
        "hours": {d: ("10:00 AM", "6:00 PM") for d in _DAYS[:5] + ["Sunday"]},
        "services": [("Poon Hill Trek", 450, "5 days"), ("Everest Base Camp Trek", 1400, "14 days"),
                     ("Day Hike Nagarkot", 60, "1 day")],
        "policies": ["30% deposit to confirm a booking", "full refund if cancelled 14 or more days before departure",
                     "trekking permits are arranged by us and included in the price"],
    },
    # Eval-only business (real Riverside Dental facts from PHASE_STATUS.md live runs). Never used in the seed/training set.
    "riverside": {
        "name": "Riverside Dental", "type": "dental clinic", "address": None, "currency": "USD",
        "hours": {d: ("9:00 AM", "5:00 PM") for d in _DAYS[:6]},
        "services": [("Cleaning", 90, "30 min")], "policies": [],
    },
}

_NOTE = "Note: you can only chat here -- you cannot actually book or change anything in this sandbox."


def _hours_line(hours: dict) -> str:
    open_days = [d for d in _DAYS if d in hours]
    closed = [d for d in _DAYS if d not in hours]
    groups, run = [], [open_days[0]]
    for d in open_days[1:]:
        if hours[d] == hours[run[-1]] and _DAYS.index(d) == _DAYS.index(run[-1]) + 1:
            run.append(d)
        else:
            groups.append(run)
            run = [d]
    groups.append(run)
    parts = [f"{g[0]}-{g[-1]} {hours[g[0]][0]}-{hours[g[0]][1]}" if len(g) > 1 else f"{g[0]} {hours[g[0]][0]}-{hours[g[0]][1]}"
             for g in groups]
    if not closed and len(set(hours.values())) == 1:
        return f"every day {hours['Monday'][0]}-{hours['Monday'][1]}."
    return "; ".join(parts) + (f". Closed {' and '.join(closed)}." if closed else ".")


def facts_text(key: str, sandbox_note: bool = True) -> str:
    """sandbox_note=False drops the 'you cannot actually book' line -- used for prompt-optimization/eval so every arm
    (including the production prompt, which CAN book) sees the same, non-contradictory facts."""
    b = BUSINESSES[key]
    services = "; ".join(f"{n} ({b['currency']} {p}, {d})" for n, p, d in b["services"])
    where = f", {b['address']}" if b["address"] else ""
    policies = f"\nPolicies: {'; '.join(b['policies'])}" if b["policies"] else ""
    return (f"Business: {b['name']} (SANDBOX - fictional), {b['type']}{where}.\n"
            f"Hours: {_hours_line(b['hours'])}\nServices: {services}{policies}" + (f"\n{_NOTE}" if sandbox_note else ""))
