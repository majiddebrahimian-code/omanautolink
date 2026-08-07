<div align="center">

# 🚗 Oman Auto Link

### Vehicle Import, Sales & Shipment Tracking Platform

**A Django-based platform for managing the complete vehicle import workflow from Oman to Iran — from vehicle publishing and customer orders to shipment tracking and Telegram automation.**

![Python](https://img.shields.io/badge/Python-3.x-blue?logo=python)
![Django](https://img.shields.io/badge/Django-Backend-green?logo=django)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-blue?logo=postgresql)
![Telegram](https://img.shields.io/badge/Telegram-Bot-blue?logo=telegram)
![Docker](https://img.shields.io/badge/Docker-Containerized-blue?logo=docker)

**Status:** 🚧 Active Development

</div>

---

## 📌 Overview

**Oman Auto Link** is a full-stack vehicle import and tracking platform designed to manage the business process of importing vehicles from Oman to Iran.

The project brings together vehicle inventory management, customer orders, shipment workflows, tracking, web administration, and Telegram automation in a unified system.

Rather than building the website and Telegram bot as separate applications, the system is designed around shared business logic and services so that multiple interfaces can operate on the same underlying workflow.

The project is being developed as a practical example of designing a real-world business system with **Python, Django, APIs, automation, and maintainable backend architecture**.

---

## ✨ Core Features

### 🚘 Vehicle Management

Administrators and authorized staff can:

- Add vehicles
- Edit vehicle information
- Upload vehicle images and videos
- Manage availability
- Publish vehicle listings
- Remove or update listings

---

### 🌐 Multi-Channel Publishing

Vehicle information can be managed through the application and integrated with Telegram workflows.

The architecture is designed so vehicle data remains centralized rather than being independently maintained across different platforms.

---

### 🤖 Telegram Bot Integration

The Telegram bot provides an additional interface for operational workflows.

It can be used by authorized staff to interact with the system without requiring access to the web administration interface for every operation.

---

### 📦 Vehicle Order Management

Customers can submit requests for available vehicles or request a specific vehicle.

The backend manages order information and connects customer requests with the import workflow.

---

### 🚢 Import Workflow Tracking

Vehicle imports move through configurable operational stages.

Examples may include:

```text
Vehicle Selected
      ↓
Order Confirmed
      ↓
Purchase Process
      ↓
Shipment Preparation
      ↓
Shipping
      ↓
Customs / Import Process
      ↓
Delivery
```

Each stage can be managed and tracked within the system.

---

### 🔎 Customer Tracking

Customers can follow the progress of their vehicle order using a tracking workflow.

The system is designed to show:

- Current stage
- Order progress
- Tracking information
- Estimated remaining process time

---

### 👥 Role-Based Access

The application separates responsibilities between different user types.

```text
Admin
Staff
Customer / Guest
```

Permissions and available operations depend on the user's role.

---

## 🏗️ Architecture

The project follows a centralized backend architecture:

```text
                     ┌─────────────────┐
                     │   Web Client    │
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │ Django Backend  │
                     └────────┬────────┘
                              │
                ┌─────────────┼─────────────┐
                │             │             │
                ▼             ▼             ▼
          Business Logic   Database    Media Management
                │
                ▼
          Telegram Services
                │
                ▼
           Telegram Bot
```

The goal is to keep business rules centralized and reusable across different interfaces.

---

## 🛠️ Technology Stack

### Backend

- Python
- Django
- Django ORM
- REST APIs

### Database

- PostgreSQL

### Automation & Integration

- Telegram Bot
- API integrations
- Automated workflow handling

### Development & Infrastructure

- Git
- GitHub
- Docker
- Linux

### Frontend

- HTML
- CSS
- JavaScript
- Responsive web interface

---

## 💡 Engineering Goals

This project focuses not only on implementing features but also on practicing real-world software engineering concepts:

- Separation of concerns
- Reusable business services
- Database modeling
- Role-based authorization
- Workflow modeling
- API integration
- External service integration
- Error handling
- Maintainable Django architecture
- Automation of repetitive business processes

---

## 📸 Screenshots

> Screenshots will be added as the user interface evolves.

<!--
Example:

### Vehicle Management

![Vehicle Management](screenshots/vehicle-management.png)

### Tracking

![Tracking](screenshots/tracking.png)

### Telegram Integration

![Telegram Bot](screenshots/telegram-bot.png)
-->

---

## 🚧 Project Status

**Oman Auto Link is currently under active development.**

The core backend architecture and major business workflows are being implemented incrementally.

Upcoming work includes further improvements to the user interface, API layer, testing, deployment, and production readiness.

---

## 🗺️ Roadmap

- [x] Core Django architecture
- [x] Vehicle management
- [x] Order workflow
- [x] Tracking workflow
- [x] Telegram integration
- [x] Role-based system
- [ ] UI/UX improvements
- [ ] Expanded REST API
- [ ] Automated testing
- [ ] CI/CD
- [ ] Production deployment
- [ ] Monitoring and logging improvements

---

## 🎯 Why I Built This Project

Oman Auto Link was created to explore how a real operational business process can be transformed into a structured software platform.

The project combines backend development, workflow automation, system integration, database design, and external services in a single application.

It also serves as an evolving portfolio project demonstrating my approach to designing and building maintainable business applications with Python and Django.

---

## 👨‍💻 Author

**Majid Ebrahimian**

Python Backend Developer | Django | APIs | AI & Automation

GitHub: [majiddebrahimian-code](https://github.com/majiddebrahimian-code)

---

## 📄 License

This project is currently maintained as a portfolio and development project.
