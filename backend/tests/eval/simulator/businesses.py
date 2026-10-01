"""Synthetic businesses the simulator chats with: many kinds, not only clinics, so a reply that only works for a dental
clinic shows up as a low score somewhere else. All data is invented; nothing here is a real business or customer.

Each spec: key, business_type (feeds style-exemplar retrieval; several types have no exemplars on purpose), name,
persona (assistant's name, or None), description, booking (does the business take bookings in chat), services
[(name, price NPR, minutes, description)], hours (open, close, closed weekdays 0=Mon..6=Sun), address, phone, faq
(knowledge base text)."""

_SAT = (5,)  # most Nepali businesses close on Saturday

BUSINESSES: list[dict] = [
    {
        "key": "dental", "business_type": "dental", "name": "Smile Care Dental", "persona": "Sita",
        "description": "a family dental clinic in Baneshwor", "booking": True,
        "services": [("Teeth Cleaning", 1500, 30, "scaling and polishing"), ("Tooth Filling", 2500, 45, "composite filling"),
                     ("Root Canal", 12000, 90, "single tooth root canal treatment")],
        "hours": ("10:00", "18:00", _SAT), "address": "New Baneshwor, Kathmandu", "phone": "01-4780001",
        "faq": "Parking: two-wheeler parking in front, no car parking. Payment: cash, eSewa, Khalti and card. "
               "Children are welcome from age 3. X-ray is done in the clinic for Rs 500.",
    },
    {
        "key": "eye", "business_type": "clinic", "name": "Netra Eye Clinic", "persona": None,
        "description": "an eye clinic for check-ups and glasses", "booking": True,
        "services": [("Eye Checkup", 800, 30, "full vision test"), ("Contact Lens Fitting", 2000, 45, "trial and fitting"),
                     ("Kids Eye Test", 600, 20, "for children under 12")],
        "hours": ("09:00", "17:00", _SAT), "address": "Lazimpat, Kathmandu", "phone": "01-4410002",
        "faq": "Glasses are ready in 3 working days. Frames start from Rs 1500. Payment by cash or Fonepay QR.",
    },
    {
        "key": "trek", "business_type": "travel", "name": "Himal Steps Trekking", "persona": "Pasang",
        "description": "a trekking agency running Everest, Annapurna and Langtang treks", "booking": True,
        "services": [("Everest Base Camp Trek", 145000, 60, "14-day guided trek, consultation call"),
                     ("Annapurna Circuit Trek", 110000, 60, "12-day guided trek, consultation call"),
                     ("Langtang Valley Trek", 65000, 60, "8-day guided trek, consultation call")],
        "hours": ("09:00", "19:00", ()), "address": "Thamel, Kathmandu", "phone": "9851000003",
        "faq": "Price includes guide, porter, permits, teahouse stays and three meals a day. Flights to Lukla are extra "
               "(about USD 220 each way). Best seasons: March-May and October-November. Group discount 10% for 4+ people.",
    },
    {
        "key": "study", "business_type": "education", "name": "Bright Path Education Consultancy", "persona": "Anu",
        "description": "a study-abroad consultancy for Australia, UK, Canada and Japan", "booking": True,
        "services": [("Counselling Session", 0, 45, "free first counselling"), ("IELTS Class", 12000, 60, "6-week course"),
                     ("Visa File Processing", 35000, 60, "documents and visa lodgement")],
        "hours": ("10:00", "17:00", _SAT), "address": "Putalisadak, Kathmandu", "phone": "01-4430004",
        "faq": "Intakes: Australia Feb/Jul/Nov, UK Jan/Sep, Canada Jan/May/Sep, Japan Apr/Oct. IELTS 6.0 overall is "
               "usually enough for a diploma. Visa fee is paid separately to the embassy.",
    },
    {
        "key": "salon", "business_type": "salon", "name": "Glow Beauty Salon", "persona": "Riya",
        "description": "a ladies beauty salon", "booking": True,
        "services": [("Haircut", 800, 45, "wash, cut and blow dry"), ("Facial", 2500, 60, "gold or fruit facial"),
                     ("Bridal Makeup", 25000, 180, "makeup, hair and draping")],
        "hours": ("10:00", "19:00", ()), "address": "Jhamsikhel, Lalitpur", "phone": "9841000005",
        "faq": "Bridal booking needs 30% advance. Products: L'Oreal and Lakme. Home service available for bridal only.",
    },
    {
        "key": "barber", "business_type": None, "name": "Kesh Gents Parlour", "persona": None,
        "description": "a gents hair cutting and shaving parlour", "booking": True,
        "services": [("Hair Cut", 300, 30, ""), ("Beard Trim", 150, 15, ""), ("Hair Colour", 1000, 45, "")],
        "hours": ("07:00", "20:00", ()), "address": "Koteshwor, Kathmandu", "phone": "9803000006",
        "faq": "Walk-ins welcome, but booked customers go first. Cash and eSewa only.",
    },
    {
        "key": "restaurant", "business_type": "restaurant", "name": "Thakali Bhanchha Ghar", "persona": None,
        "description": "a Thakali restaurant", "booking": True,
        "services": [("Table Reservation", 0, 90, "table for up to 8 people"), ("Thakali Khana Set", 650, 60, "veg set"),
                     ("Party Package", 1200, 180, "per person, minimum 20 people")],
        "hours": ("11:00", "22:00", ()), "address": "Durbarmarg, Kathmandu", "phone": "01-4220007",
        "faq": "Non-veg set (chicken/mutton) Rs 850. Home delivery through Foodmandu only. Vegan options available.",
    },
    {
        "key": "cafe", "business_type": None, "name": "Himalayan Java Corner", "persona": "Bikash",
        "description": "a coffee shop with small cakes and snacks", "booking": False,
        "services": [("Cappuccino", 280, 5, ""), ("Chocolate Cake Slice", 320, 5, ""), ("Birthday Cake 1 pound", 1400, 1440, "order a day before")],
        "hours": ("07:00", "21:00", ()), "address": "Pulchowk, Lalitpur", "phone": "9801000008",
        "faq": "Free wifi. Pet friendly outdoor seating. Custom cakes need one day notice.",
    },
    {
        "key": "grocery", "business_type": "retail", "name": "Himal Organic Store", "persona": None,
        "description": "an organic food shop with home delivery", "booking": False,
        "services": [("Organic Rice 5kg", 950, 0, "Jumla red rice"), ("Wild Honey 500g", 1200, 0, ""), ("Home Delivery", 100, 0, "inside ring road")],
        "hours": ("08:00", "20:00", ()), "address": "Baluwatar, Kathmandu", "phone": "9802000009",
        "faq": "Delivery same day for orders before 2pm. Free delivery above Rs 3000. Payment on delivery or eSewa.",
    },
    {
        "key": "gym", "business_type": "fitness", "name": "Iron Paradise Gym", "persona": None,
        "description": "a gym with personal training and zumba", "booking": True,
        "services": [("Monthly Membership", 3500, 60, "unlimited access"), ("Personal Training Session", 1500, 60, ""),
                     ("Zumba Class", 500, 60, "drop-in class")],
        "hours": ("05:30", "21:00", ()), "address": "Chabahil, Kathmandu", "phone": "9813000010",
        "faq": "Separate ladies hour 1-3pm. Lockers free. Admission fee Rs 1000 one time. Steam bath included.",
    },
    {
        "key": "yoga", "business_type": "fitness", "name": "Shanti Yoga Studio", "persona": "Maya",
        "description": "a yoga and meditation studio", "booking": True,
        "services": [("Morning Yoga Class", 400, 60, ""), ("Meditation Course", 5000, 60, "10 sessions"),
                     ("Private Yoga", 2000, 60, "one to one")],
        "hours": ("06:00", "19:00", _SAT), "address": "Boudha, Kathmandu", "phone": "9840000011",
        "faq": "Mats provided. Beginners welcome. Come on an empty stomach.",
    },
    {
        "key": "hotel", "business_type": "hospitality", "name": "Lakeside Comfort Hotel", "persona": None,
        "description": "a hotel by Phewa lake", "booking": True,
        "services": [("Standard Room per night", 3500, 1440, "double bed, breakfast"), ("Deluxe Lake View per night", 6500, 1440, "breakfast"),
                     ("Airport Pickup", 1000, 60, "Pokhara airport")],
        "hours": ("00:00", "23:59", ()), "address": "Lakeside, Pokhara", "phone": "061-460012",
        "faq": "Check-in 12pm, check-out 11am. Free wifi and parking. Boating can be arranged.",
    },
    {
        "key": "lawyer", "business_type": "legal", "name": "Nyaya Law Associates", "persona": None,
        "description": "a law firm for property, family and company matters", "booking": True,
        "services": [("Legal Consultation", 3000, 45, ""), ("Company Registration", 25000, 60, "full process"),
                     ("Property Document Review", 8000, 60, "")],
        "hours": ("10:00", "17:00", _SAT), "address": "Anamnagar, Kathmandu", "phone": "01-4100013",
        "faq": "Consultations in person or on video. Fees do not include government charges.",
    },
    {
        "key": "garage", "business_type": None, "name": "Speed Bike Workshop", "persona": None,
        "description": "a motorbike and scooter servicing workshop", "booking": True,
        "services": [("Full Servicing", 1200, 120, "engine oil extra"), ("Engine Oil Change", 900, 30, ""),
                     ("Brake Repair", 600, 45, "")],
        "hours": ("08:00", "18:00", _SAT), "address": "Kalanki, Kathmandu", "phone": "9818000014",
        "faq": "Pick and drop available inside ring road for Rs 300. Genuine parts only.",
    },
    {
        "key": "school", "business_type": "education", "name": "Little Stars Montessori", "persona": None,
        "description": "a preschool for ages 2 to 5", "booking": True,
        "services": [("School Visit", 0, 30, "meet the teachers"), ("Monthly Fee", 9000, 30, "includes snacks"),
                     ("Day Care per day", 800, 480, "")],
        "hours": ("08:00", "16:00", _SAT), "address": "Sanepa, Lalitpur", "phone": "01-5520015",
        "faq": "Admission fee Rs 15000. School van available for Rs 2500 per month. Class size max 15.",
    },
    {
        "key": "tuition", "business_type": "education", "name": "Gyan Tuition Centre", "persona": None,
        "description": "tuition for grade 8 to 12 science and maths", "booking": True,
        "services": [("SEE Maths Class", 3000, 60, "per month"), ("Grade 12 Physics", 4000, 60, "per month"),
                     ("Trial Class", 0, 60, "")],
        "hours": ("06:00", "19:00", _SAT), "address": "Kirtipur", "phone": "9849000016",
        "faq": "Morning batch 6-7am and evening batch 5-6pm. Max 20 students per batch.",
    },
    {
        "key": "vet", "business_type": "clinic", "name": "Paws Pet Clinic", "persona": None,
        "description": "a veterinary clinic for dogs and cats", "booking": True,
        "services": [("Pet Checkup", 700, 30, ""), ("Vaccination", 1200, 20, "rabies or DHPPi"), ("Pet Grooming", 1500, 60, "")],
        "hours": ("09:00", "19:00", ()), "address": "Bhaisepati, Lalitpur", "phone": "9808000017",
        "faq": "Emergency: call the clinic phone. Pet food and accessories also sold.",
    },
    {
        "key": "photo", "business_type": None, "name": "Click Moments Studio", "persona": None,
        "description": "a photo studio for weddings, passports and events", "booking": True,
        "services": [("Passport Photo", 300, 15, "4 copies"), ("Wedding Package", 85000, 480, "photo and video"),
                     ("Pre-Wedding Shoot", 30000, 240, "")],
        "hours": ("09:00", "19:00", ()), "address": "New Road, Kathmandu", "phone": "9841000018",
        "faq": "Wedding package needs 50% advance. Edited photos delivered in 3 weeks.",
    },
    {
        "key": "it", "business_type": None, "name": "Fix It Laptop Repair", "persona": None,
        "description": "a laptop and phone repair shop", "booking": True,
        "services": [("Laptop Diagnosis", 500, 30, "free if repaired here"), ("Screen Replacement", 6500, 120, "depends on model"),
                     ("Windows Installation", 800, 60, "")],
        "hours": ("10:00", "19:00", _SAT), "address": "Putalisadak, Kathmandu", "phone": "9803000019",
        "faq": "3 months warranty on parts. Data backup Rs 500.",
    },
    {
        "key": "realestate", "business_type": None, "name": "Ghar Jagga Realty", "persona": None,
        "description": "a real estate agency for buying and renting houses and land", "booking": True,
        "services": [("Property Visit", 0, 60, "free site visit"), ("Rental Listing", 2000, 30, "for owners")],
        "hours": ("10:00", "18:00", _SAT), "address": "Budhanilkantha, Kathmandu", "phone": "9851000020",
        "faq": "Commission is 2% for sale, one month's rent for rentals. Listings in Kathmandu valley only.",
    },
    {
        "key": "driving", "business_type": "education", "name": "Safe Drive Training Centre", "persona": None,
        "description": "a driving school for car and scooter", "booking": True,
        "services": [("Car Driving Course", 18000, 60, "30 days, 1 hour daily"), ("Scooter Course", 8000, 60, "15 days")],
        "hours": ("06:00", "18:00", ()), "address": "Balkhu, Kathmandu", "phone": "9849000021",
        "faq": "Trial for licence test included. Ladies trainer available.",
    },
    {
        "key": "tailor", "business_type": None, "name": "Silai Ghar Tailors", "persona": None,
        "description": "a tailor for kurta, suits and alterations", "booking": False,
        "services": [("Kurta Stitching", 1500, 0, "7 days"), ("Suit Stitching", 6000, 0, "14 days"), ("Alteration", 200, 0, "")],
        "hours": ("10:00", "19:00", _SAT), "address": "Ason, Kathmandu", "phone": "9803000022",
        "faq": "Urgent stitching in 2 days for 50% extra. Customer brings own fabric or chooses from our shop.",
    },
    {
        "key": "event", "business_type": None, "name": "Utsav Party Palace", "persona": None,
        "description": "a party palace for weddings, bratabandha and birthdays", "booking": True,
        "services": [("Hall Booking Visit", 0, 45, "see the hall"), ("Wedding Package per plate", 1400, 30, "minimum 300 guests")],
        "hours": ("09:00", "18:00", ()), "address": "Tinkune, Kathmandu", "phone": "01-4110023",
        "faq": "Hall capacity 800. Decoration included. Parking for 100 cars.",
    },
    {
        "key": "physio", "business_type": "clinic", "name": "MoveWell Physiotherapy", "persona": "Asha",
        "description": "a physiotherapy centre for back, neck and sports injuries", "booking": True,
        "services": [("Physio Session", 1200, 45, ""), ("Back Pain Package", 10000, 45, "10 sessions"),
                     ("Home Visit", 2500, 60, "")],
        "hours": ("07:00", "19:00", _SAT), "address": "Maharajgunj, Kathmandu", "phone": "9841000024",
        "faq": "Doctor's referral not needed. Wear loose clothes.",
    },
]

BY_KEY = {b["key"]: b for b in BUSINESSES}
