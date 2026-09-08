#JSON examples for Reservation Service
{
  "user_id": 40,
  "pharmacy_id": 2,
  "medicine_name": "BIOGESIC 250MG SYR 60ML ORANGE",
  "price": 140.57,
  "quantity": 2,
  "notes": "Will pick up during morning shift",
  "contact_no": "09760667737",
  "email": "rosesarewhat13@gmail.com",
  "time_slot": "9:00 AM",
  "prescription": "PRESC_1776106.jpg"
}

#JSON examples for Inventory Service
{
  "status": "success",
  "data": {
    "medicine_id": 2,
    "medicine_name": "BIOGESIC 250MG SYR 60ML ORANGE",
    "batch_no": "L030014",
    "category": "Pain Relievers",
    "price": 140.57,
    "quantity": 57,
    "prescription_required": "no",
    "expiration_date": "2027-01-31",
    "pharmacy_id": 2,
    "stock_status": "Adequate"
  }
}
