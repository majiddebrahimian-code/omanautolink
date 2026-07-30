import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import StaffProfile
from accounts.services import RoleGroup, ensure_default_role_groups
from cars.models import Car
from integrations.models import (
    TelegramInboundUpdate,
    TelegramOutboxMessage,
    TelegramStageConfirmationSession,
    TelegramStaffLink,
    TelegramStaffLinkToken,
)
from integrations.services import (
    create_telegram_staff_link_code,
    deliver_telegram_outbox_message,
    ingest_and_process_telegram_update,
    link_staff_telegram_account,
    queue_telegram_message,
)
from integrations.telegram.gateway import TelegramGatewayTransientError
from tracking.models import CarStageProgress, Stage, StageTransition, TrackingEvent
from tracking.services import start_tracking_for_sold_car


class FakeSuccessfulTelegramGateway:
    def __init__(self):
        self.sent_messages = []
        self.callback_answers = []

    def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        return {"message_id": 12345}

    def answer_callback_query(self, **kwargs):
        self.callback_answers.append(kwargs)
        return True


class FakeTransientTelegramGateway:
    def send_message(self, **kwargs):
        raise TelegramGatewayTransientError("temporary failure")

    def answer_callback_query(self, **kwargs):
        raise TelegramGatewayTransientError("temporary failure")


class TelegramIntegrationBaseTests(TestCase):
    def setUp(self):
        self.role_groups = ensure_default_role_groups()
        user_model = get_user_model()

        self.administrator = user_model.objects.create_superuser(
            username="telegram-system-administrator",
            password="test-password",
        )
        self.clearance_employee = user_model.objects.create_user(
            username="telegram-clearance-employee",
            password="test-password",
            is_staff=True,
        )
        self.clearance_employee.groups.add(
            self.role_groups[RoleGroup.CLEARANCE_EMPLOYEE]
        )

        self.sale_confirmed_stage = Stage.objects.create(
            name="Sale Confirmed",
            order=1,
        )
        self.clearance_stage = Stage.objects.create(
            name="Customs Clearance",
            order=2,
        )
        StageTransition.objects.create(
            from_stage=self.sale_confirmed_stage,
            to_stage=self.clearance_stage,
            estimated_duration_days=5,
        )

        profile = StaffProfile.objects.create(user=self.clearance_employee)
        profile.assigned_stages.add(self.clearance_stage)

        self.car = Car.objects.create(
            title="Toyota Land Cruiser",
            brand="Toyota",
            model="Land Cruiser",
            status=Car.Status.SOLD,
            tracking_code="OAL-telegram-test-car",
        )
        start_tracking_for_sold_car(
            car=self.car,
            actor=self.administrator,
        )

    def issue_link_code(self, *, staff_user=None):
        return create_telegram_staff_link_code(
            staff_user=staff_user or self.clearance_employee,
            actor=self.administrator,
        )

    def link_staff(self, *, staff_user=None, telegram_user_id=700001, telegram_chat_id=700001):
        issued_code = self.issue_link_code(staff_user=staff_user)
        return link_staff_telegram_account(
            code=issued_code["code"],
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_username="clearance_user",
            first_name="Clearance",
        )

    def message_update(self, *, update_id, text, telegram_user_id=700001, telegram_chat_id=700001):
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id + 100,
                "from": {
                    "id": telegram_user_id,
                    "username": "clearance_user",
                    "first_name": "Clearance",
                },
                "chat": {
                    "id": telegram_chat_id,
                    "type": "private",
                },
                "text": text,
            },
        }

    def callback_update(
        self,
        *,
        update_id,
        callback_data,
        telegram_user_id=700001,
        telegram_chat_id=700001,
    ):
        return {
            "update_id": update_id,
            "callback_query": {
                "id": f"callback-{update_id}",
                "from": {
                    "id": telegram_user_id,
                    "username": "clearance_user",
                    "first_name": "Clearance",
                },
                "message": {
                    "message_id": update_id + 100,
                    "chat": {
                        "id": telegram_chat_id,
                        "type": "private",
                    },
                },
                "data": callback_data,
            },
        }


class TelegramStaffLinkServiceTests(TelegramIntegrationBaseTests):
    def test_link_code_is_one_time_and_only_its_hash_is_persisted(self):
        issued_code = self.issue_link_code()

        self.assertTrue(issued_code["code"].startswith("TGL-"))
        self.assertNotEqual(issued_code["token"].code_hash, issued_code["code"])
        self.assertFalse(hasattr(issued_code["token"], "code"))

        staff_link = link_staff_telegram_account(
            code=issued_code["code"],
            telegram_user_id=700001,
            telegram_chat_id=700001,
            telegram_username="clearance_user",
        )

        issued_code["token"].refresh_from_db()
        self.assertTrue(staff_link.is_active)
        self.assertIsNotNone(issued_code["token"].used_at)
        self.assertEqual(issued_code["token"].used_telegram_user_id, 700001)

        with self.assertRaises(ValidationError):
            link_staff_telegram_account(
                code=issued_code["code"],
                telegram_user_id=700001,
                telegram_chat_id=700001,
            )

        issued_code["token"].refresh_from_db()
        self.assertEqual(issued_code["token"].attempt_count, 2)

    def test_only_system_administrator_can_issue_a_staff_link_code(self):
        with self.assertRaises(ValidationError):
            create_telegram_staff_link_code(
                staff_user=self.clearance_employee,
                actor=self.clearance_employee,
            )

    def test_relinking_keeps_history_and_only_one_active_link(self):
        first_link = self.link_staff()
        second_link = self.link_staff(
            telegram_user_id=700002,
            telegram_chat_id=700002,
        )

        first_link.refresh_from_db()
        self.assertFalse(first_link.is_active)
        self.assertTrue(second_link.is_active)
        self.assertEqual(
            TelegramStaffLink.objects.filter(
                user=self.clearance_employee,
                is_active=True,
            ).count(),
            1,
        )


class TelegramBotStageConfirmationTests(TelegramIntegrationBaseTests):
    def test_start_command_links_staff_and_does_not_store_raw_link_code(self):
        issued_code = self.issue_link_code()

        ingest_and_process_telegram_update(
            update=self.message_update(
                update_id=1001,
                text=f"/start {issued_code['code']}",
            )
        )

        inbound_update = TelegramInboundUpdate.objects.get(telegram_update_id=1001)
        self.assertEqual(inbound_update.status, TelegramInboundUpdate.Status.PROCESSED)
        self.assertEqual(inbound_update.command_name, "/start")
        self.assertIsNotNone(inbound_update.staff_link)
        self.assertTrue(
            TelegramOutboxMessage.objects.filter(
                inbound_update=inbound_update,
                message_type="link_success",
            ).exists()
        )
        self.assertEqual(TelegramStaffLinkToken.objects.count(), 1)

    def test_confirm_command_creates_preview_for_the_expected_stage(self):
        self.link_staff()

        ingest_and_process_telegram_update(
            update=self.message_update(
                update_id=1002,
                text=f"/confirm {self.car.tracking_code}",
            )
        )

        confirmation_session = TelegramStageConfirmationSession.objects.get()
        preview_message = TelegramOutboxMessage.objects.get(
            message_type="confirmation_preview"
        )

        self.assertEqual(confirmation_session.car, self.car)
        self.assertEqual(confirmation_session.stage, self.clearance_stage)
        self.assertEqual(
            confirmation_session.status,
            TelegramStageConfirmationSession.Status.PENDING,
        )
        self.assertIn("inline_keyboard", preview_message.reply_markup)
        self.assertEqual(
            CarStageProgress.objects.get(
                car=self.car,
                stage=self.clearance_stage,
            ).state,
            "pending",
        )

    def test_callback_confirmation_uses_shared_tracking_service_and_telegram_source(self):
        self.link_staff()
        ingest_and_process_telegram_update(
            update=self.message_update(
                update_id=1003,
                text=f"/confirm {self.car.tracking_code}",
            )
        )
        confirmation_session = TelegramStageConfirmationSession.objects.get()

        ingest_and_process_telegram_update(
            update=self.callback_update(
                update_id=1004,
                callback_data=f"confirm:{confirmation_session.public_token}",
            )
        )

        self.car.refresh_from_db()
        confirmation_session.refresh_from_db()
        progress = CarStageProgress.objects.get(
            car=self.car,
            stage=self.clearance_stage,
        )
        event = TrackingEvent.objects.get(
            car=self.car,
            event_type=TrackingEvent.EventType.STAGE_CONFIRMED,
        )

        self.assertEqual(self.car.current_stage, self.clearance_stage)
        self.assertEqual(progress.confirmed_by, self.clearance_employee)
        self.assertEqual(event.source, TrackingEvent.Source.TELEGRAM_BOT)
        self.assertEqual(event.performed_by, self.clearance_employee)
        self.assertEqual(
            confirmation_session.status,
            TelegramStageConfirmationSession.Status.CONFIRMED,
        )
        self.assertTrue(
            TelegramOutboxMessage.objects.filter(
                message_type="confirmation_success"
            ).exists()
        )

    def test_duplicate_callback_update_creates_only_one_tracking_event(self):
        self.link_staff()
        ingest_and_process_telegram_update(
            update=self.message_update(
                update_id=1005,
                text=f"/confirm {self.car.tracking_code}",
            )
        )
        confirmation_session = TelegramStageConfirmationSession.objects.get()
        callback = self.callback_update(
            update_id=1006,
            callback_data=f"confirm:{confirmation_session.public_token}",
        )

        first_result = ingest_and_process_telegram_update(update=callback)
        second_result = ingest_and_process_telegram_update(update=callback)

        self.assertFalse(first_result["duplicate"])
        self.assertTrue(second_result["duplicate"])
        self.assertEqual(
            TrackingEvent.objects.filter(
                car=self.car,
                event_type=TrackingEvent.EventType.STAGE_CONFIRMED,
            ).count(),
            1,
        )

    def test_general_employee_cannot_create_a_confirmation_preview(self):
        user_model = get_user_model()
        general_employee = user_model.objects.create_user(
            username="telegram-general-employee",
            password="test-password",
            is_staff=True,
        )
        general_employee.groups.add(self.role_groups[RoleGroup.EMPLOYEE])
        profile = StaffProfile.objects.create(user=general_employee)
        profile.assigned_stages.add(self.clearance_stage)

        self.link_staff(
            staff_user=general_employee,
            telegram_user_id=800001,
            telegram_chat_id=800001,
        )
        ingest_and_process_telegram_update(
            update=self.message_update(
                update_id=1007,
                text=f"/confirm {self.car.tracking_code}",
                telegram_user_id=800001,
                telegram_chat_id=800001,
            )
        )

        self.assertFalse(TelegramStageConfirmationSession.objects.exists())
        self.assertTrue(
            TelegramOutboxMessage.objects.filter(
                message_type="confirmation_preview_failed"
            ).exists()
        )
        self.assertFalse(
            TrackingEvent.objects.filter(
                car=self.car,
                event_type=TrackingEvent.EventType.STAGE_CONFIRMED,
            ).exists()
        )

    def test_another_linked_staff_member_cannot_confirm_someone_elses_session(self):
        first_link = self.link_staff()

        user_model = get_user_model()
        second_employee = user_model.objects.create_user(
            username="second-telegram-clearance-employee",
            password="test-password",
            is_staff=True,
        )
        second_employee.groups.add(self.role_groups[RoleGroup.CLEARANCE_EMPLOYEE])
        second_profile = StaffProfile.objects.create(user=second_employee)
        second_profile.assigned_stages.add(self.clearance_stage)
        self.link_staff(
            staff_user=second_employee,
            telegram_user_id=900001,
            telegram_chat_id=900001,
        )

        ingest_and_process_telegram_update(
            update=self.message_update(
                update_id=1008,
                text=f"/confirm {self.car.tracking_code}",
                telegram_user_id=first_link.telegram_user_id,
                telegram_chat_id=first_link.telegram_chat_id,
            )
        )
        confirmation_session = TelegramStageConfirmationSession.objects.get()

        ingest_and_process_telegram_update(
            update=self.callback_update(
                update_id=1009,
                callback_data=f"confirm:{confirmation_session.public_token}",
                telegram_user_id=900001,
                telegram_chat_id=900001,
            )
        )

        confirmation_session.refresh_from_db()
        self.assertEqual(
            confirmation_session.status,
            TelegramStageConfirmationSession.Status.PENDING,
        )
        self.assertFalse(
            TrackingEvent.objects.filter(
                car=self.car,
                event_type=TrackingEvent.EventType.STAGE_CONFIRMED,
            ).exists()
        )


class TelegramOutboxTests(TelegramIntegrationBaseTests):
    def test_outbox_delivery_uses_gateway_and_records_success(self):
        outbox_message = queue_telegram_message(
            chat_id=700001,
            body="پیام آزمایشی",
            message_type="test",
            idempotency_key="outbox-success-test",
        )
        gateway = FakeSuccessfulTelegramGateway()

        result = deliver_telegram_outbox_message(
            outbox_id=outbox_message.pk,
            gateway=gateway,
        )

        outbox_message.refresh_from_db()
        self.assertEqual(result["outcome"], "sent")
        self.assertEqual(outbox_message.status, TelegramOutboxMessage.Status.SENT)
        self.assertEqual(outbox_message.telegram_message_id, 12345)
        self.assertEqual(len(gateway.sent_messages), 1)

    @override_settings(TELEGRAM_OUTBOX_MAX_ATTEMPTS=2)
    def test_transient_outbox_failure_retries_then_fails_at_the_limit(self):
        outbox_message = queue_telegram_message(
            chat_id=700001,
            body="پیام آزمایشی",
            message_type="test",
            idempotency_key="outbox-retry-test",
        )

        first_result = deliver_telegram_outbox_message(
            outbox_id=outbox_message.pk,
            gateway=FakeTransientTelegramGateway(),
        )
        outbox_message.refresh_from_db()

        self.assertEqual(first_result["outcome"], "retry")
        self.assertEqual(outbox_message.status, TelegramOutboxMessage.Status.RETRY)

        outbox_message.next_attempt_at = timezone.now() - timedelta(seconds=1)
        outbox_message.save(update_fields=["next_attempt_at"])
        second_result = deliver_telegram_outbox_message(
            outbox_id=outbox_message.pk,
            gateway=FakeTransientTelegramGateway(),
        )
        outbox_message.refresh_from_db()

        self.assertEqual(second_result["outcome"], "failed")
        self.assertEqual(outbox_message.status, TelegramOutboxMessage.Status.FAILED)
        self.assertEqual(outbox_message.attempt_count, 2)


class TelegramWebhookTests(TelegramIntegrationBaseTests):
    @override_settings(
        TELEGRAM_BOT_ENABLED=True,
        TELEGRAM_WEBHOOK_SECRET="test-webhook-secret",
    )
    def test_webhook_requires_secret_and_accepts_a_valid_update(self):
        url = reverse("integrations:telegram_webhook")
        update = self.message_update(update_id=1010, text="/help")

        forbidden_response = self.client.post(
            url,
            data=json.dumps(update),
            content_type="application/json",
        )
        valid_response = self.client.post(
            url,
            data=json.dumps(update),
            content_type="application/json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="test-webhook-secret",
        )

        self.assertEqual(forbidden_response.status_code, 403)
        self.assertEqual(valid_response.status_code, 200)
        self.assertEqual(valid_response.json(), {"ok": True, "duplicate": False})
