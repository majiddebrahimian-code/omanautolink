# 🚗 Oman Auto Link

### Vehicle Import, Sales & Delivery Tracking Platform

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python\&logoColor=white)
![Django](https://img.shields.io/badge/Django-5-green?logo=django\&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-blue?logo=postgresql\&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-Cache%20%26%20Broker-red?logo=redis\&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-Background%20Tasks-green?logo=celery\&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Containerized-blue?logo=docker\&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-blue?logo=telegram\&logoColor=white)

A production-oriented Django platform for managing **vehicle sales, import operations, delivery tracking, customer requests, and Telegram workflows** for vehicles imported from Oman to Iran.

Oman Auto Link is designed as a real-world operational system with centralized business logic, asynchronous processing, role-based permissions, configurable workflows, and Telegram integration.

---

## 📌 Overview

Oman Auto Link centralizes the complete operational lifecycle of an imported vehicle — from inventory and customer negotiation to shipment tracking and final delivery.

```text
Vehicle Inventory
        ↓
Temporary Reservation
        ↓
Customer Negotiation
        ↓
Manual Sale Confirmation
        ↓
Tracking Code Assignment
        ↓
Configurable Delivery Stages
        ↓
Customer Tracking
        ↓
Final Delivery
```

A key architectural goal of the project is to **avoid duplicated business logic**.

The Website, Backoffice, Telegram Bot, Telegram Channel, Excel Import, and background workers all rely on shared Django business services rather than implementing independent workflows.

---

# ✨ Main Features

## 🚘 Vehicle Management

* Vehicle inventory management
* Unique vehicle codes
* Multiple vehicle images and videos
* Featured vehicle support
* Vehicle availability management
* Temporary reservation during customer negotiation
* Manual sale confirmation
* Vehicle media management

## 📦 Delivery & Tracking

* Unique tracking code generation
* Configurable linear delivery stages
* Stage receive / complete workflow
* Vehicle delivery history
* Operational audit events
* Public customer tracking without requiring an account
* Rate limiting for public tracking requests

## 👥 Users & Permissions

* Role-based access control
* Permission-based staff access
* Administrator and employee roles
* Stage-specific clearance employee permissions
* Controlled access to operational actions
* Staff management through the Backoffice

## 🤖 Telegram Integration

* Telegram Bot integration for staff operations
* Customer tracking notifications
* Telegram Channel vehicle publishing
* Vehicle media synchronization
* Shared workflows between Telegram and web interfaces
* Background notification processing
* Telegram Outbox architecture

## 📊 Excel Operations

* Bulk tracking-stage updates
* Excel import workflow
* Input validation before processing
* Operational support for large tracking updates
* OpenPyXL-based spreadsheet processing

## 🌐 Public Website

* Persian RTL interface
* Vehicle listings
* Vehicle detail pages
* Public shipment tracking
* Custom vehicle request form
* Contact form with persistent message storage
* SEO configuration
* Blog and content management
* Dynamic homepage content
* Configurable Header and Footer
* Dynamic social links and navigation

## 🖥️ Backoffice

* Custom Persian RTL operational dashboard
* Vehicle operations
* Customer management
* Tracking management
* Staff and permission management
* Website content configuration
* Blog management
* Operational workflow management

---

# 🏗️ Architecture

One of the main engineering principles behind Oman Auto Link is **centralized business logic**.

Instead of implementing separate business rules for the Website, Backoffice, Telegram Bot, imports, and background workers, these interfaces communicate through shared Django services.

```text
                Website / Backoffice
                        │
                        ▼
               ┌──────────────────┐
               │  Shared Services │
               └──────────────────┘
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
         PostgreSQL        Background Workers
                                  │
                            Redis / Celery
                                  │
                ┌─────────────────┴─────────────────┐
                ▼                                   ▼
          Telegram Bot                      Telegram Channel
```

This architecture keeps core business rules centralized and makes the application easier to:

* Maintain
* Test
* Extend
* Integrate with new interfaces
* Run asynchronously

---

# 🛠️ Technology Stack

| Area                   | Technology            |
| ---------------------- | --------------------- |
| Language               | Python 3.12           |
| Backend Framework      | Django 5              |
| Database               | PostgreSQL            |
| Cache / Message Broker | Redis                 |
| Background Jobs        | Celery                |
| Task Scheduler         | Celery Beat           |
| Containers             | Docker Compose        |
| Frontend               | HTML, CSS, JavaScript |
| Interface              | Persian RTL           |
| Messaging              | Telegram Bot API      |
| Excel Processing       | OpenPyXL              |

---

# 📁 Project Structure

```text
oman-auto-link/
│
├── accounts/
│   └── Users, roles, permissions and staff management
│
├── backoffice/
│   └── Custom Persian RTL operational dashboard
│
├── blog/
│   └── Magazine, categories, posts and SEO content
│
├── cars/
│   └── Inventory, media, sales, reservations and vehicle codes
│
├── core/
│   └── Public website, site settings, SEO, static pages and contact form
│
├── customers/
│   └── Customer profiles and custom vehicle requests
│
├── integrations/
│   └── Telegram Bot, channel publishing, outbox and notifications
│
├── tracking/
│   └── Delivery stages, tracking codes, history and Excel import
│
├── config/
│   └── Django settings, URLs and Celery configuration
│
├── manage.py
├── docker-compose.yml
├── .env.example
└── README.md
```

---

# 🔄 Core Business Workflow

A typical vehicle transaction follows this workflow:

```text
1. Vehicle added to inventory
              ↓
2. Vehicle published
              ↓
3. Customer begins negotiation
              ↓
4. Vehicle temporarily reserved
              ↓
5. Sale manually confirmed
              ↓
6. Unique tracking code generated
              ↓
7. Vehicle enters delivery workflow
              ↓
8. Staff update delivery stages
              ↓
9. Customer tracks vehicle
              ↓
10. Vehicle delivered
```

Delivery stages are configurable, allowing the operational workflow to evolve without hardcoding the complete delivery process.

---

# 🚀 Local Development

## 1. Clone the repository

```bash
git clone <repository-url>
cd oman-auto-link
```

## 2. Create environment variables

```bash
cp .env.example .env
```

Configure the required database credentials, Telegram configuration, and application secrets inside `.env`.

> ⚠️ **Never commit `.env` or production credentials to the repository.**

---

## 3. Build and start the project

```bash
docker compose up --build
```

---

## 4. Apply database migrations

```bash
docker compose exec web python manage.py migrate
```

---

## 5. Create an administrator

```bash
docker compose exec web python manage.py createsuperuser
```

---

## 6. Open the application

**Public Website**

```text
http://127.0.0.1:8000/
```

**Backoffice**

```text
http://127.0.0.1:8000/panel/
```

---

# 🧪 Testing

Run the Django test suite:

```bash
docker compose exec web python manage.py test
```

---

# 🔐 Security

The project follows several security practices:

* Application secrets are stored using environment variables
* Telegram tokens are kept outside source control
* Database credentials are not committed
* Public tracking requests are rate-limited
* Operational actions are protected by role and permission checks
* Private and local uploaded media should not be committed
* Sensitive configuration is separated from application code

Before production deployment, additional production-level configuration is required, including:

* HTTPS
* Secure cookies
* Production `ALLOWED_HOSTS`
* CSRF configuration
* Production database configuration
* Centralized logging
* Application monitoring
* Database backups
* Production-grade secret management

---

# 📸 Screenshots

<img width="1346" height="585" alt="image" src="https://github.com/user-attachments/assets/60a3f0f4-ba1f-4b01-a6b9-0bd7b1aaa622" />
<img width="1345" height="595" alt="image" src="https://github.com/user-attachments/assets/62ba2683-9657-453a-ad43-c3858f30c666" />


Recommended structure:

```text
docs/
└── screenshots/
    ├── homepage.png
    ├── vehicle-list.png
    ├── vehicle-details.png
    ├── tracking.png
    ├── backoffice.png
    └── telegram-bot.png
```

Once screenshots are available, they can be displayed directly inside this README.

---

# 🗺️ Roadmap

### Core Platform

* [x] Vehicle inventory management
* [x] Vehicle media management
* [x] Temporary customer reservation
* [x] Manual sale confirmation
* [x] Tracking code generation
* [x] Configurable delivery stages
* [x] Delivery history and audit events

### Operations

* [x] Role and permission system
* [x] Clearance staff permissions
* [x] Excel tracking import
* [x] Persian RTL Backoffice
* [x] Public customer tracking

### Integrations

* [x] Telegram Bot integration
* [x] Telegram Channel publishing
* [x] Vehicle media synchronization
* [x] Background task processing

### Public Platform & Production

* [ ] Final public website UI/UX
* [ ] Complete end-to-end testing
* [ ] CI/CD pipeline
* [ ] Production monitoring and logging
* [ ] Production deployment
* [ ] Final user acceptance testing

---

# 🚧 Project Status

### Active Development

The **core operational backend, tracking system, Backoffice, and Telegram workflows are implemented**.

Current development is focused on:

* Final public website UI/UX
* Production hardening
* CI/CD
* Monitoring and logging
* End-to-end testing
* Final user acceptance testing

The repository represents an actively evolving portfolio project rather than a finished commercial release.

---

# 🎯 Engineering Focus

Oman Auto Link was built as a practical implementation of real-world software engineering concepts, including:

* Domain modeling
* Service-layer architecture
* Role-based access control
* Permission management
* Business workflow design
* Audit trails
* Asynchronous background processing
* Telegram integrations
* Data import pipelines
* Operational dashboards
* PostgreSQL data modeling
* Redis-based infrastructure
* RTL user interface development
* SEO-managed content
* Maintainable Django architecture

---

# 👨‍💻 Author

### Majid Ebrahimian

**Software Engineer | Python & Django | AI-Powered Application Development**

Focused on designing and building practical software systems, backend applications, automation workflows, and AI-integrated solutions.

**GitHub:** `majiddebrahimian-code`

---

# 📄 License

This project is currently maintained as a **portfolio and active development project**.

Licensing terms may be added in a future release.

---

⭐ If you find the architecture or implementation useful, feel free to explore the repository.
