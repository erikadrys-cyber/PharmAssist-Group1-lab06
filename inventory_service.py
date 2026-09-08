from csv import DictReader, DictWriter
from pathlib import Path
import xml.etree.ElementTree as ET

from flask import Flask, jsonify, request, Response
from werkzeug.exceptions import BadRequest

app = Flask(__name__)

DATA_FILE = Path(__file__).parent / "data" / "medicines.csv"


# ---------------------------------------------------------
# CSV FUNCTIONS
# ---------------------------------------------------------

def load_medicines():
    with DATA_FILE.open(
        "r",
        encoding="utf-8",
        newline=""
    ) as file:
        medicines = list(DictReader(file))

    for medicine in medicines:
        medicine["medicine_id"] = int(
            medicine["medicine_id"]
        )
        medicine["price"] = float(
            medicine["price"]
        )
        medicine["quantity"] = int(
            medicine["quantity"]
        )
        medicine["pharmacy_id"] = int(
            medicine["pharmacy_id"]
        )

    return medicines


def save_medicines(medicines):
    fieldnames = [
        "medicine_id",
        "medicine_name",
        "batch_no",
        "category",
        "price",
        "quantity",
        "prescription_required",
        "expiration_date",
        "pharmacy_id",
        "stock_status"
    ]

    with DATA_FILE.open(
        "w",
        encoding="utf-8",
        newline=""
    ) as file:

        writer = DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(medicines)


# ---------------------------------------------------------
# XML SERIALIZATION
# ---------------------------------------------------------

def medicine_to_xml(medicine):
    root = ET.Element("InventoryResponse")

    status = ET.SubElement(root, "status")
    status.text = "success"

    data = ET.SubElement(root, "data")

    for key, value in medicine.items():
        element = ET.SubElement(data, key)
        element.text = str(value)

    return ET.tostring(
        root,
        encoding="unicode"
    )


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------

@app.get("/health")
def health():
    return jsonify({
        "service": "inventory-service",
        "status": "UP"
    }), 200

# ---------------------------------------------------------
# XML PARSING (Part 6)
# ---------------------------------------------------------

def xml_to_dict(xml_bytes):
    """Converts an incoming <reservation> XML body into a plain dict
    with the same shape as the JSON body PharmAssist already expects."""
    root = ET.fromstring(xml_bytes)
    return {child.tag: child.text for child in root}


def reservation_to_xml(reservation):
    """Serializes a reservation dict back into XML for the response."""
    root = ET.Element("reservation")
    for key, value in reservation.items():
        element = ET.SubElement(root, key)
        element.text = str(value)
    return ET.tostring(root, encoding="unicode")


# ---------------------------------------------------------
# GET ALL MEDICINES
# ---------------------------------------------------------

@app.get("/medicines")
def get_medicines():
    return jsonify(load_medicines()), 200


# ---------------------------------------------------------
# GET MEDICINE BY ID
# WITH CONTENT NEGOTIATION
# ---------------------------------------------------------

@app.get("/medicines/<int:medicine_id>")
def get_medicine(medicine_id):

    medicines = load_medicines()

    medicine = next(
        (
            medicine
            for medicine in medicines
            if medicine["medicine_id"]
            == medicine_id
        ),
        None
    )

    if medicine is None:
        return jsonify({
            "error": "Medicine not found"
        }), 404

    requested_type = (
        request.accept_mimetypes.best_match(
            [
                "application/json",
                "application/xml"
            ]
        )
    )

    if requested_type == "application/xml":

        xml_data = medicine_to_xml(
            medicine
        )

        return Response(
            xml_data,
            status=200,
            mimetype="application/xml"
        )

    return jsonify(medicine), 200


# ---------------------------------------------------------
# UPDATE MEDICINE STOCK
# ---------------------------------------------------------

@app.put("/medicines/<int:medicine_id>")
def update_medicine_stock(medicine_id):

    # -----------------------------------------------------
    # 1. Check Content-Type
    # -----------------------------------------------------

    if not request.is_json:
        return jsonify({
            "error": "Unsupported Content-Type",
            "message": "Use application/json"
        }), 415

    # -----------------------------------------------------
    # 2. Read JSON
    # -----------------------------------------------------

    try:
        data = request.get_json()
    except BadRequest:
        return jsonify({
            "error": "Malformed JSON"
        }), 400

    if not isinstance(data, dict):
        return jsonify({
            "error": "Invalid request body"
        }), 400

    # -----------------------------------------------------
    # 3. Find medicine
    # -----------------------------------------------------

    medicines = load_medicines()

    medicine = next(
        (
            medicine
            for medicine in medicines
            if medicine["medicine_id"]
            == medicine_id
        ),
        None
    )

    if medicine is None:
        return jsonify({
            "error": "Medicine not found"
        }), 404

    # -----------------------------------------------------
    # 4. Validate quantity field
    # -----------------------------------------------------

    if (
        "quantity" not in data
        or data["quantity"] in [None, ""]
    ):
        return jsonify({
            "error": "Missing required field",
            "field": "quantity"
        }), 400

    # -----------------------------------------------------
    # 5. Validate quantity value
    # -----------------------------------------------------

    try:
        quantity = int(
            data["quantity"]
        )

    except (ValueError, TypeError):
        return jsonify({
            "error": "Quantity must be a number"
        }), 400

    if quantity < 0:
        return jsonify({
            "error": "Quantity cannot be negative"
        }), 400

    # -----------------------------------------------------
    # 6. Update medicine
    # -----------------------------------------------------

    medicine["quantity"] = quantity

    if quantity == 0:
        medicine["stock_status"] = (
            "Out of Stock"
        )

    elif quantity <= 20:
        medicine["stock_status"] = (
            "Low Stock"
        )

    else:
        medicine["stock_status"] = (
            "Adequate"
        )

    save_medicines(medicines)

    # -----------------------------------------------------
    # 7. Return updated medicine
    # -----------------------------------------------------

    return jsonify({
        "message":
            "Medicine stock updated successfully",
        "data": medicine
    }), 200


# ---------------------------------------------------------
# RUN SERVICE
# ---------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5002,
        debug=False
    )