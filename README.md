# PharmAssist

A microservices-based e-pharmacy backend that lets customers check medicine stock and reserve medicines across multiple pharmacy branches through a Reservation Service and Inventory Service integrated behind a single API Gateway.

## 1. Project Overview

PharmAssist is a web-based e-pharmacy platform built to solve a common problem in retail and community pharmacies: customers have no reliable way to check medicine availability, compare prices, or reserve a product across multiple branches without physically visiting each one. In a traditional setup, a customer walks into a branch, asks if a medicine is in stock, checks the price, and if it isn't available, has to repeat the process at another branch. Comparing prices across generic-equivalent brands is also difficult without this kind of legwork.

This is compounded by the fact that many pharmacy systems and data sources (inventory systems, EHRs, e-prescribing systems, HIE platforms) operate independently or with limited interoperability, which leads to delayed access to information, repeated data handling, and inconsistent records across systems.

PharmAssist addresses this by providing a common platform where medicine, inventory, pricing, reservation, and branch information can be accessed by authorized users and connected systems. Long-term, the project aims to expand PharmAssist into an integrated system that supports:

- Real-time branch location lookup (e.g. via Google Maps API) so customers can find the nearest branch with their needed medicine in stock.
- Image-based medicine search through product packaging scanning.
- Automated extraction of medicine details (name, dosage, batch number, expiration date) from product packaging using OCR.
- Digitization of doctor's handwritten prescriptions via text recognition, to help elderly customers and those with difficulty reading handwriting — while still requiring pharmacist verification before a reservation is approved.
- Secure, role-based access control (email verification, ID verification, password reset) so system data is only available to authenticated, approved users appropriate to their role.

This repository implements the **first phase** of that vision: a microservices-based backend that lets a customer check medicine stock and create a reservation, with the Reservation Service and Inventory Service communicating with each other through a REST API, and both exposed behind a single API Gateway.

---

## 2. Microservice Architecture

The system is split into two independently running services, each owning its own data and responsibilities.

| Item | Reservation Service (A) | Inventory Service (B) |
|---|---|---|
| **Business Responsibility** | Handles reservation creation, claim-code generation, and status/lifecycle tracking. | Tracks real-time medicine stock per branch and supplier info. |
| **Main Resource / Data** | Reservation: `user_id`, `medicine`, `quantity`, `branch`, `status`, `claim_code`. | Medicine/Inventory: `medicine_id`, `name`, `stock quantity`, `branch_id`. |
| **Example Operations** | Create reservation, check reservation status, update status (approved, cancelled, expired). | Get stock for a medicine, get all medicines for a branch, update stock quantity. |
| **Reason for Separation** | Reservation logic changes independently — claim windows, statuses — and should not be blocked by inventory updates. | Inventory is updated by many actors (staff, suppliers, other reservations). Keeping it separate avoids the reservation service owning stock data it doesn't control. |

Separating these two concerns means each service can evolve, scale, and fail independently: a slowdown in stock updates from suppliers doesn't block reservation lookups, and changes to reservation/claim logic don't require redeploying the inventory system.

---

## 3. Architecture Diagram

```
                     Client / Postman
                            |
                            v
                     API Gateway
                (routes and authenticates)
                     (localhost:8000)
                    /                \
                   v                  v
      Reservation Service       Inventory Service
       (localhost:5001)          (localhost:5002)
      Reservation, claim   ---->  Stock levels per branch
            codes            "Checks stock"
                   |                  |
                   v                  v
        Reservations Database   Medicines Database
```

- **Client / Postman** — sends all requests to a single entry point, the API Gateway.
- **API Gateway (localhost:8000)** — routes incoming requests to the correct backend service based on URL path prefix, and is the only address the client needs to know.
- **Reservation Service (localhost:5001)** — owns reservation creation and claim-code/status logic; calls the Inventory Service to verify stock before confirming a reservation.
- **Inventory Service (localhost:5002)** — owns medicine and stock records per branch; responds to both direct client requests (via the gateway) and internal calls from the Reservation Service.
- **Service-to-service communication** — the Reservation Service calls `GET /medicines/{id}` on the Inventory Service (`Accept: application/json`) before creating any reservation, to confirm enough stock exists.

---

## 4. API Documentation

### Reservation Service (`http://127.0.0.1:5001`)

| Method | Endpoint | Purpose | Expected Input | Response |
|---|---|---|---|---|
| GET | `/health` | Checks whether the Reservation Service is running. | None | `200 OK` — `{ "service": "reservation-service", "status": "UP" }` |
| GET | `/reservations/{id}` | Retrieves a specific reservation by its ID. | Path parameter: `id` (integer) | `200 OK` with reservation object (`claim_code`, `contact_no`, `email`, `medicine_id`, `medicine_name`, `notes`, `pharmacy_id`, `prescription`, `price`, `quantity`, `reservation_id`, `status`, `time_slot`, `user_id`); `404` if not found |
| POST | `/reservations` | Creates a new reservation. Internally checks stock via the Inventory Service before confirming. Accepts either JSON (`Content-Type: application/json`) or XML (`Content-Type: application/xml`). | Body fields: `user_id`, `medicine_id`, `pharmacy_id`, `quantity`, `contact_no`, `email`, `time_slot` (JSON), or the equivalent `<reservation>` XML element | `201 Created` with the full reservation record (including server-generated `reservation_id`, `claim_code`, `status: "Pending"`), serialized in the same format the request was sent (JSON or XML); `400/404/409/415/503` on error (see Section 6) |

### Inventory Service (`http://127.0.0.1:5002`)

| Method | Endpoint | Purpose | Expected Input | Response |
|---|---|---|---|---|
| GET | `/health` | Checks whether the Inventory Service is running. | None | `200 OK` — `{ "service": "inventory-service", "status": "UP" }` |
| GET | `/medicines/{id}` | Retrieves stock information for a specific medicine. Supports content negotiation via the `Accept` header (`application/json` or `application/xml`). | Path parameter: `id` (integer); header: `Accept` | `200 OK` with medicine record (`batch_no`, `category`, `expiration_date`, `medicine_id`, `medicine_name`, `pharmacy_id`, `prescription_required`, `price`, `quantity`, `stock_status`) in JSON or XML depending on `Accept`; `404` if not found |
| PUT | `/medicines/{id}` | Updates the stock quantity for a specific medicine. | Path parameter: `id`; body: updated `quantity` (and/or other stock fields) | `200 OK` with the updated medicine record; `400/404` on error |

### API Gateway (`http://127.0.0.1:8000`)

| Incoming Path | Routed To | Service Base URL |
|---|---|---|
| `/api/reservations/*` | Reservation Service | `http://localhost:5001` |
| `/api/medicines/*` | Inventory Service | `http://localhost:5002` |
| `/health` | API Gateway itself | `http://localhost:8000` |

The gateway forwards requests unchanged to the matching backend service and returns `503 Service Unavailable` or `504 Gateway Timeout` if the target service can't be reached in time (see Section 6).

---

## 5. Data Representation

PharmAssist supports **both JSON and XML** as request/response formats, so the same underlying data can be exchanged with clients that prefer either format.

### JSON

Used by default for both services. Example reservation request body (Reservation Service):

```json
{
  "user_id": 77,
  "medicine_id": 2,
  "quantity": 1,
  "pharmacy_id": 2,
  "contact_no": "09000000000",
  "email": "customer@example.com",
  "time_slot": "2:00 PM"
}
```

Example inventory response (Inventory Service):

```json
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
```

### XML

Used as an alternative representation for the same resources, selected either by sending the request body as XML or by setting `Accept: application/xml` on a `GET` request. Example reservation request body:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<ReservationRequest>
  <user_id>40</user_id>
  <pharmacy_id>2</pharmacy_id>
  <medicine_name>BIOGESIC 250MG SYR 60ML ORANGE</medicine_name>
  <price>140.57</price>
  <quantity>2</quantity>
  <notes>Will pick up during morning shift</notes>
  <contact_no>09760667737</contact_no>
  <email>rosesarewhat13@gmail.com</email>
  <time_slot>9:00 AM</time_slot>
  <prescription>PRESC_1776106.jpg</prescription>
</ReservationRequest>
```

Example inventory response:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<InventoryResponse>
  <status>success</status>
  <data>
    <medicine_id>2</medicine_id>
    <medicine_name>BIOGESIC 250MG SYR 60ML ORANGE</medicine_name>
    <batch_no>L030014</batch_no>
    <category>Pain Relievers</category>
    <price>140.57</price>
    <quantity>57</quantity>
    <prescription_required>no</prescription_required>
    <expiration_date>2027-01-31</expiration_date>
    <pharmacy_id>2</pharmacy_id>
    <stock_status>Adequate</stock_status>
  </data>
</InventoryResponse>
```

**How the services handle both formats:**
1. **Parsing** — the `Content-Type` header determines how the request body is read: `request.get_json()` for JSON, `xml.etree.ElementTree` for XML.
2. **Deserialization** — the parsed body (a dict for JSON, or a dict built from `{child.tag: child.text for child in root}` for XML) is converted into a plain Python dictionary shape shared by both formats.
3. **Validation** — required fields (e.g. `medicine_id`, `quantity`, `pharmacy_id`) are checked for presence and correct type/value (e.g. `quantity > 0`) before the request reaches business logic.
4. **Business processing** — the service layer executes the actual logic (e.g. checking stock, generating a reservation ID and claim code).
5. **Serialization** — the result is serialized back into whichever format the client sent/requested (`jsonify()` for JSON, `ET.tostring()` for XML), with a matching response `Content-Type` header.

For the Inventory Service's `GET /medicines/{id}` endpoint specifically, the response format is chosen through **content negotiation** based on the `Accept` header (`request.accept_mimetypes.best_match([...])`), rather than the request body.

---

## 6. Integration Flow

**Business Transaction:** Before the Reservation Service creates a reservation, it must confirm with the Inventory Service that enough stock exists.

```
POST /reservations
        |
        v
Reservation Service
        |  needs medicine stock info
        |  GET /medicines/{id}
        |  Accept: application/json
        v
Inventory Service
        |  serializes medicine record
        v
   JSON Response
        |
        v
Reservation Service
        |  deserializes JSON
        v
Validation: requested quantity <= available stock
        |
        v
Create Reservation (reservation_id, status = "pending")
        |
        v
Serialize response back to client (JSON or XML)
```

**Steps:**
1. A client sends `POST /reservations` (JSON or XML body) to the Reservation Service.
2. The Reservation Service parses, deserializes, and validates the request.
3. Before creating the reservation, it calls `GET /medicines/{medicine_id}` on the Inventory Service with `Accept: application/json`.
4. The Inventory Service looks up the medicine and returns its current stock as a JSON response.
5. The Reservation Service deserializes that response and validates that the requested quantity is less than or equal to the available stock.
6. If stock is sufficient, the Reservation Service generates a `reservation_id` and `claim_code`, sets `status: "pending"`, and stores the record.
7. The completed reservation is serialized back to the client in the same format the original request used.

**Failure cases in this flow:**
- **Not enough stock → `409 Conflict`** — the request conflicts with the current inventory state (same concept as a duplicate/conflicting operation).
- **Inventory Service down or unreachable → `503 Service Unavailable`** — the Reservation Service cannot complete stock verification.

---

## 7. Error Handling

### `reservation_service.py`

| Scenario | HTTP Response |
|---|---|
| Malformed XML | `400 Bad Request` — `{"error": "MALFORMED_XML", "message": "Request body is not valid XML"}` |
| Malformed JSON | `400 Bad Request` — `{"error": "Malformed JSON"}` |
| Missing required field (e.g. `quantity`) | `400 Bad Request` — `{"error": "Missing required field", "field": "quantity"}` |
| Medicine not found | `404 Not Found` — `{"error": "Medicine not found"}` |
| Insufficient stock (requested quantity > available stock) | `409 Conflict` — `{"error": "Insufficient stock", "message": "The requested quantity is greater than the available stock.", "requested_quantity": ..., "available_quantity": ...}` |

### `inventory_service.py`

| Scenario | HTTP Response |
|---|---|
| Unsupported content type (not `application/json`) | `415 Unsupported Media Type` — `{"error": "Unsupported Content-Type", "message": "Use application/json"}` |

### `api_gateway.py`

| Scenario | HTTP Response |
|---|---|
| Target microservice unreachable | `503 Service Unavailable` — `{"error": "SERVICE_UNAVAILABLE", "message": "Target microservice is unreachable"}` |
| Target microservice timeout | `504 Gateway Timeout` — `{"error": "GATEWAY_TIMEOUT", "message": "Target microservice timed out"}` |

Additionally, system-controlled fields (e.g. `medicine_name`, `price`) submitted by the client on reservation creation are rejected with `400 Bad Request` — `{"error": "System-controlled fields cannot be submitted", "fields": [...]}`.

---

## 8. Installation and Execution

### Prerequisites
- Python 3.10+
- pip
- [Postman](https://www.postman.com/downloads/) (for testing)

### Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/<your-username>/PharmAssist_Lab05.git
   cd PharmAssist_Lab05
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # macOS / Linux
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the Inventory Service** (in its own terminal)
   ```bash
   python inventory_service.py
   ```
   Starts on `http://127.0.0.1:5002`.

5. **Run the Reservation Service** (in a second terminal)
   ```bash
   python reservation_service.py
   ```
   Starts on `http://127.0.0.1:5001`.

6. **Run the API Gateway** (in a third terminal, if included in your setup)
   ```bash
   python api_gateway.py
   ```
   Starts on `http://127.0.0.1:8000` and routes to both services above.

7. **Verify everything is running**
   ```bash
   curl http://127.0.0.1:5001/health
   curl http://127.0.0.1:5002/health
   curl http://127.0.0.1:8000/health
   ```
   Each should return `{"status": "UP"}`.

### Project Structure

```
PharmAssist_Lab05/
├── .venv/
├── data/
│   ├── medicines.csv
│   └── reservations.csv
├── inventory_service.py
├── reservation_service.py
├── api_gateway.py
├── requirements.txt
└── README.md
```

---

## 9. Testing (Postman Collection)

A Postman collection is included to exercise every endpoint and error scenario described above.

### How to use it
1. Open Postman and click **Import**.
2. Select the collection file included in this repository (e.g. `PharmAssist.postman_collection.json`).
3. Make sure all three services (Reservation, Inventory, and API Gateway) are running locally, per Section 8.
4. Run requests individually, or right-click the collection and choose **Run collection** to execute the full suite in order.
5. Check the **Test Results** tab on each request to confirm the expected status code was returned.

### Included test requests

| # | Postman Request | Expected Result |
|---|---|---|
| 01 | Reservation Service Health | `200 OK` |
| 02 | Inventory Service Health | `200 OK` |
| 03 | Get Medicine – JSON | `200 OK` |
| 04 | Get Medicine – XML | `200 OK` |
| 05 | Create Reservation – JSON | `201 Created` |
| 06 | Create Reservation – XML | `201 Created` |
| 07 | Missing Required Field | `400 Bad Request` |
| 08 | Malformed JSON | `400 Bad Request` |
| 09 | Malformed XML | `400 Bad Request` |
| 10 | Reservation Not Found | `400 Bad Request` |
| 11 | Unsupported Media Type | `415 Unsupported Media Type` |
| 12 | Create Reservation – Integrated Transaction | `201 Created` |
| 13 | Create Reservation – Failed Integration | `503 Service Unavailable` |

These requests together validate: service health, JSON/XML content negotiation, successful reservation creation in both formats, input validation, error handling for malformed payloads, and the Reservation ↔ Inventory service-to-service integration (including the failure path when the Inventory Service is unreachable).
