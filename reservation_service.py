from csv import DictReader, DictWriter
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET

import requests
from flask import Flask, jsonify, request, Response
from werkzeug.exceptions import BadRequest

app = Flask(__name__)

DATA_FILE = Path(__file__).parent / "data" / "reservations.csv"

INVENTORY_SERVICE_URL = "http://127.0.0.1:5002"


# ---------------------------------------------------------
# LOAD RESERVATIONS FROM CSV
# ---------------------------------------------------------

def load_reservations():
    with DATA_FILE.open("r", encoding="utf-8", newline="") as file:
        reservations = list(DictReader(file))

    for reservation in reservations:
        reservation["reservation_id"] = int(
            reservation["reservation_id"]
        )
        reservation["user_id"] = int(
            reservation["user_id"]
        )
        reservation["medicine_id"] = int(
            reservation["medicine_id"]
        )
        reservation["price"] = float(
            reservation["price"]
        )
        reservation["quantity"] = int(
            reservation["quantity"]
        )
        reservation["pharmacy_id"] = int(
            reservation["pharmacy_id"]
        )

    return reservations


# ---------------------------------------------------------
# SAVE RESERVATIONS TO CSV
# ---------------------------------------------------------

def save_reservations(reservations):
    # These are the fields currently stored for each PharmAssist reservation record
    fieldnames = [
        "reservation_id",
        "user_id",
        "medicine_id",
        "medicine_name",
        "price",
        "quantity",
        "pharmacy_id",
        "status",
        "claim_code",
        "notes",
        "contact_no",
        "email",
        "time_slot",
        "prescription"
    ]

    # Rewrites reservations.csv with the latest reservation records
    with DATA_FILE.open("w", encoding="utf-8", newline="") as file:
        writer = DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reservations)


# ---------------------------------------------------------
# XML PARSING / SERIALIZATION
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
# HEALTH CHECK
# ---------------------------------------------------------

@app.get("/health")
def health():
    return jsonify({
        "service": "reservation-service",
        "status": "UP"
    }), 200


# ---------------------------------------------------------
# GET RESERVATION BY ID
# ---------------------------------------------------------

@app.get("/reservations/<int:reservation_id>")
def get_reservation(reservation_id):

    reservations = load_reservations()

    # Searches for the reservation matching the ID entered 
    reservation = next(
        (
            reservation
            for reservation in reservations
            if reservation["reservation_id"] == reservation_id
        ),
        None
    )

    # If the reservation ID does not exist, returns a 404 error
    if reservation is None:
        return jsonify({
            "error": "Reservation not found",
            "message": f"No reservation exists with reservation ID {reservation_id}."
    }), 404


# ---------------------------------------------------------
# CREATE NEW RESERVATION
# ---------------------------------------------------------

@app.post("/reservations")
def create_reservation():

    # -----------------------------------------------------
    # CHECK REQUEST FORMAT
    # -----------------------------------------------------

    content_type = request.content_type or ""
    is_xml_request = "application/xml" in content_type

    if is_xml_request:
        try:
            data = xml_to_dict(request.data)
        except ET.ParseError:
            return jsonify({
                "error": "MALFORMED_XML",
                "message": "Request body is not valid XML"
            }), 400

    elif request.is_json:
        try:
            data = request.get_json()
        except BadRequest:
            return jsonify({
                "error": "Malformed JSON",
                "message": "The request body contains invalid JSON syntax. Please check the JSON format and try again."
            }), 400

        if not isinstance(data, dict):
            return jsonify({
                "error": "Invalid request body",
                "message": "The request body must contain a valid reservation object."
            }), 400

    else:
        return jsonify({
            "error": "Unsupported Content-Type",
            "message": "This endpoint only accepts application/json or application/xml."
        }), 415


    # -----------------------------------------------------
    # PROTECT SYSTEM-CONTROLLED FIELDS
    # -----------------------------------------------------

    # PharmAssist will generate or retrieve these fields automatically
    system_fields = [
        "reservation_id",
        "medicine_name",
        "price",
        "status",
        "claim_code"
    ]

    # Checks if the customer tried to submit any system-controlled field
    invalid_fields = [
        field
        for field in system_fields
        if field in data
    ]

    # Rejects the request if the customer tries to manually set fields such as status or claim_code
    if invalid_fields:
        return jsonify({
            "error": "System-controlled fields cannot be submitted",
            "message": "These fields are generated or controlled by PharmAssist and cannot be entered by the customer.",
            "fields": invalid_fields
        }), 400


    # -----------------------------------------------------
    # VALIDATE CUSTOMER INPUT
    # -----------------------------------------------------

    # These are the minimum details needed to create a reservation
    required_fields = [
        "user_id",
        "medicine_id",
        "quantity",
        "pharmacy_id",
        "contact_no",
        "email",
        "time_slot"
    ]

    # Checks which required fields are missing or empty
    missing_fields = [
        field
        for field in required_fields
        if field not in data
        or data[field] in [None, ""]
    ]

    if missing_fields:
        return jsonify({
            "error": "Missing required field",
            "message": "Please provide all required reservation information before submitting the request.",
            "fields": missing_fields
        }), 400


    # -----------------------------------------------------
    # VALIDATE QUANTITY
    # -----------------------------------------------------

    # Converts the requested quantity to an integer
    try:
        quantity = int(data["quantity"])

    except (ValueError, TypeError):
        return jsonify({
            "error": "Quantity must be a number",
            "message": "Quantity must be entered as a whole number."
        }), 400

    # Customers cannot reserve zero or a negative quantity
    if quantity <= 0:
        return jsonify({
            "error": "Quantity must be greater than 0",
            "message": "Quantity must be greater than 0."
        }), 400


    # -----------------------------------------------------
    # VALIDATE IDs
    # -----------------------------------------------------

    # Converts the IDs sent by the client into integers
    try:
        user_id = int(data["user_id"])
        medicine_id = int(data["medicine_id"])
        pharmacy_id = int(data["pharmacy_id"])

    except (ValueError, TypeError):
        return jsonify({
            "error": (
                "user_id, medicine_id, and "
                "pharmacy_id must be numbers",
            )
        }), 400


    # -----------------------------------------------------
    # CONTACT INVENTORY SERVICE
    # -----------------------------------------------------

    # Before a reservation is created, the Reservation Service asks
    # the Inventory Service for the selected medicine's current details.
    #
    # This keeps inventory data inside the Inventory Service instead of
    # letting the Reservation Service directly access medicines.csv.
    try:
        inventory_response = requests.get(
            f"{INVENTORY_SERVICE_URL}/medicines/{medicine_id}",
            headers={
                "Accept": "application/json"
            },
            timeout=3
        )

    # If Inventory Service takes too long to respond
    except requests.exceptions.Timeout:
        return jsonify({
            "error": "Inventory Service timeout",
            "message": "The Inventory Service did not respond within the allowed time. Please try again."
        }), 503

    # If Inventory Service is not running or cannot be reached
    except requests.exceptions.ConnectionError:
        return jsonify({
            "error": "Inventory Service unavailable",
            "message": "The reservation cannot be completed because the Inventory Service is currently unavailable."
        }), 503

    except requests.exceptions.RequestException:
        return jsonify({
            "error": "Unable to communicate with Inventory Service",
            "message": "PharmAssist was unable to communicate with the Inventory Service."
        }), 503


    # -----------------------------------------------------
    # CHECK IF MEDICINE EXISTS
    # -----------------------------------------------------

    # Inventory Service returns 404 when the medicine ID does not exist
    if inventory_response.status_code == 404:
        return jsonify({
            "error": "Medicine not found",
            "message": f"No medicine exists with medicine ID {medicine_id}."
        }), 404

    if inventory_response.status_code != 200:
        return jsonify({
            "error": "Inventory Service request failed",
            "message": "The Inventory Service returned an unexpected response and the reservation could not be completed."
        }), 502

    medicine = inventory_response.json()


    # -----------------------------------------------------
    # CHECK SELECTED PHARMACY
    # -----------------------------------------------------

    # Confirms that the selected medicine belongs to the pharmacy chosen by the customer
    if int(medicine["pharmacy_id"]) != pharmacy_id:
        return jsonify({
            "error": (
                "Medicine is not available "
                "at the selected pharmacy",
            ),
            "message": "The selected medicine is not available at the pharmacy chosen for this reservation."
        }), 409


    # -----------------------------------------------------
    # CHECK STOCK AVAILABILITY
    # -----------------------------------------------------

    available_stock = int(medicine["quantity"])

    # The reservation is not created if the requested quantity is > than the available stock
    if quantity > available_stock:
        return jsonify({
            "error": "Insufficient stock",
            "message": "The requested quantity is greater than the available stock.",
            "requested_quantity": quantity,
            "available_quantity": available_stock
        }), 409


    # -----------------------------------------------------
    # GENERATE RESERVATION ID
    # -----------------------------------------------------

    reservations = load_reservations()

    # Generates the next reservation ID based on the highest reservation ID currently stored in reservations.csv
    if reservations:
        reservation_id = max(
            reservation["reservation_id"]
            for reservation in reservations
        ) + 1
    else:
        # If there are no existing reservations yet, PharmAssist starts reservation IDs at 501
        reservation_id = 501


    # -----------------------------------------------------
    # GENERATE CLAIM CODE
    # -----------------------------------------------------

    # PharmAssist automatically generates the claim code
    claim_code = (
        f"RES-{datetime.now().year}-{reservation_id}"
    )


    # -----------------------------------------------------
    # BUILD THE RESERVATION RECORD
    # -----------------------------------------------------

    new_reservation = {

        # Generated automatically by PharmAssist.
        "reservation_id": reservation_id,

        # For now, the user_id is provided by the customer, but in a real-world scenario, it would be from logging in to PharmAssist
        "user_id": user_id,
        "medicine_id": medicine_id,

        # Medicine name and price are retrieved from Inventory Service, so the customer cannot manually change them
        "medicine_name": medicine["medicine_name"],
        "price": float(medicine["price"]),

        # Details entered or selected by the customer
        "quantity": quantity,
        "pharmacy_id": pharmacy_id,
        "notes": data.get("notes", ""),
        "contact_no": data["contact_no"],
        "email": data["email"],
        "time_slot": data["time_slot"],
        "prescription": data.get("prescription", ""),

        # Since the separate reservation validation/approval process has not yet been implemented, all newly created
        # reservations are initially placed under Pending status
        "status": "Pending",

        # The generated code
        "claim_code": claim_code
    }


    # -----------------------------------------------------
    # SAVE RESERVATION
    # -----------------------------------------------------

    # Adds the newly created reservation to the existing records
    reservations.append(new_reservation)

    # Updates reservations.csv so the new reservation is permanently stored
    save_reservations(reservations)


    # -----------------------------------------------------
    # RETURN RESULT TO CUSTOMER
    # -----------------------------------------------------

    # If the customer sent XML, respond with XML so the format is consistent
    if is_xml_request:
        xml_body = reservation_to_xml(new_reservation)
        return Response(xml_body, status=201, content_type="application/xml")

    # Sends the completed reservation back to the customer, including the generated reservation ID, status, and claim code
    return jsonify({
        "message": "Reservation created successfully",
        "data": new_reservation
    }), 201


# ---------------------------------------------------------
# RUN RESERVATION SERVICE
# ---------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5001,
        debug=False
    )