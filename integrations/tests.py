import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import StaffProfile
from accounts.services import RoleGroup, ensure_default_role_groups
from cars.models import Car
from customers.models import Customer, SearchLog
from integrations.models import (
    CustomerTelegramSubscription,
    CustomerTrackingNotification,
    TelegramCustomerActivationToken,
    TelegramInboundUpdate,
    TelegramOutboxMessage,
    TelegramStageConfirmationSession,
    TelegramStaffLink,
    TelegramStaffLinkToken,
)
from integrations.services import (
    activate_customer_telegram_tracking,
    create_customer_telegram_activation_code,
    create_telegram_staff_link_code,
    deliver_telegram_outbox_message,
    ingest_and_process_telegram_update,
    link_staff_telegram_account,
    queue_telegram_message,
    retry_failed_telegram_outbox_message,
    unsubscribe_customer_telegram_tracking,
)
from integrations.telegram.gateway import TelegramGatewayTransientError
from tracking.models import CarStageProgress, Stage, StageTransition, TrackingEvent
from tracking.services import confirm_stage, start_tracking_for_sold_car


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

        self.customer = Customer.objects.create(
            full_name="Telegram Customer",
            phone="09120000000",
            telegram_id="legacy-customer-telegram-id",
        )

        self.car = Car.objects.create(
            title="Toyota Land Cruiser",
            brand="Toyota",
            model="Land Cruiser",
            status=Car.Status.SOLD,
            tracking_code="OAL-telegram-test-car",
            customer=self.customer,
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

    def issue_customer_activation_code(self):
        return create_customer_telegram_activation_code(
            car=self.car,
            actor=self.administrator,
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


class TelegramCustomerActivationServiceTests(TelegramIntegrationBaseTests):
    def test_only_a_system_administrator_or_explicitly_authorized_employee_can_reissue_code(self):
        with self.assertRaises(ValidationError):
            create_customer_telegram_activation_code(
                car=self.car,
                actor=self.clearance_employee,
            )

    def test_customer_activation_code_is_one_time_and_raw_value_is_not_persisted(self):
        issued_code = self.issue_customer_activation_code()

        self.assertTrue(issued_code["code"].startswith("TGC-"))
        self.assertNotEqual(issued_code["token"].code_hash, issued_code["code"])
        self.assertFalse(hasattr(issued_code["token"], "code"))

        subscription = activate_customer_telegram_tracking(
            code=issued_code["code"],
            telegram_user_id=810001,
            telegram_chat_id=810001,
            first_name="Customer",
        )

        issued_code["token"].refresh_from_db()
        self.assertTrue(subscription.is_active)
        self.assertEqual(subscription.car, self.car)
        self.assertEqual(subscription.customer, self.customer)
        self.assertIsNotNone(issued_code["token"].used_at)
        self.assertEqual(issued_code["token"].used_telegram_user_id, 810001)

        with self.assertRaises(ValidationError):
            activate_customer_telegram_tracking(
                code=issued_code["code"],
                telegram_user_id=810001,
                telegram_chat_id=810001,
            )

        issued_code["token"].refresh_from_db()
        self.assertEqual(issued_code["token"].attempt_count, 2)

    def test_reissuing_customer_code_revokes_the_previous_unused_code(self):
        first_code = self.issue_customer_activation_code()
        second_code = self.issue_customer_activation_code()

        first_code["token"].refresh_from_db()

        self.assertIsNotNone(first_code["token"].revoked_at)
        self.assertIsNone(second_code["token"].revoked_at)
        self.assertEqual(TelegramCustomerActivationToken.objects.count(), 2)

        with self.assertRaises(ValidationError):
            activate_customer_telegram_tracking(
                code=first_code["code"],
                telegram_user_id=810002,
                telegram_chat_id=810002,
            )

    def test_new_activation_replaces_an_existing_active_subscription_for_same_car(self):
        first_code = self.issue_customer_activation_code()
        first_subscription = activate_customer_telegram_tracking(
            code=first_code["code"],
            telegram_user_id=810003,
            telegram_chat_id=810003,
        )
        second_code = self.issue_customer_activation_code()
        second_subscription = activate_customer_telegram_tracking(
            code=second_code["code"],
            telegram_user_id=810004,
            telegram_chat_id=810004,
        )

        first_subscription.refresh_from_db()

        self.assertFalse(first_subscription.is_active)
        self.assertTrue(second_subscription.is_active)
        self.assertEqual(
            CustomerTelegramSubscription.objects.filter(
                car=self.car,
                is_active=True,
            ).count(),
            1,
        )


class TelegramCustomerBotTests(TelegramIntegrationBaseTests):
    def test_customer_start_command_activates_subscription_and_returns_safe_status(self):
        issued_code = self.issue_customer_activation_code()

        ingest_and_process_telegram_update(
            update=self.message_update(
                update_id=2001,
                text=f"/start {issued_code['code']}",
                telegram_user_id=820001,
                telegram_chat_id=820001,
            )
        )

        inbound_update = TelegramInboundUpdate.objects.get(telegram_update_id=2001)
        reply = TelegramOutboxMessage.objects.get(
            inbound_update=inbound_update,
            message_type="customer_activation_success",
        )

        self.assertIsNotNone(inbound_update.customer_subscription)
        self.assertEqual(
            inbound_update.customer_subscription.telegram_user_id,
            820001,
        )
        self.assertIn(self.car.tracking_code, reply.body)
        self.assertNotIn(self.customer.phone, reply.body)
        self.assertFalse(hasattr(inbound_update, "command_argument"))
        self.assertTrue(
            SearchLog.objects.filter(source=SearchLog.Source.BOT, car=self.car).exists()
        )

    def test_unlinked_customer_can_use_track_and_success_is_logged_as_bot_lookup(self):
        ingest_and_process_telegram_update(
            update=self.message_update(
                update_id=2002,
                text=f"/track {self.car.tracking_code}",
                telegram_user_id=820002,
                telegram_chat_id=820002,
            )
        )

        self.assertTrue(
            TelegramOutboxMessage.objects.filter(
                message_type="customer_tracking_lookup",
            ).exists()
        )
        search_log = SearchLog.objects.get(source=SearchLog.Source.BOT)
        self.assertEqual(search_log.car, self.car)
        self.assertEqual(search_log.customer, self.customer)

    def test_status_lists_the_active_customer_subscriptions(self):
        issued_code = self.issue_customer_activation_code()
        activate_customer_telegram_tracking(
            code=issued_code["code"],
            telegram_user_id=820003,
            telegram_chat_id=820003,
        )

        ingest_and_process_telegram_update(
            update=self.message_update(
                update_id=2003,
                text="/status",
                telegram_user_id=820003,
                telegram_chat_id=820003,
            )
        )

        status_reply = TelegramOutboxMessage.objects.get(
            message_type="customer_tracking_status"
        )
        self.assertIn(self.car.tracking_code, status_reply.body)
        self.assertIn("تاریخچهٔ مراحل", status_reply.body)

    def test_stop_unsubscribes_only_the_requested_vehicle(self):
        issued_code = self.issue_customer_activation_code()
        activate_customer_telegram_tracking(
            code=issued_code["code"],
            telegram_user_id=820004,
            telegram_chat_id=820004,
        )

        ingest_and_process_telegram_update(
            update=self.message_update(
                update_id=2004,
                text=f"/stop {self.car.tracking_code}",
                telegram_user_id=820004,
                telegram_chat_id=820004,
            )
        )

        self.assertFalse(
            CustomerTelegramSubscription.objects.get(car=self.car).is_active
        )
        self.assertTrue(
            TelegramOutboxMessage.objects.filter(
                message_type="customer_stop_success"
            ).exists()
        )


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "telegram-tracking-rate-limit-tests",
        }
    },
    TELEGRAM_TRACKING_RATE_LIMIT_ATTEMPTS=3,
    TELEGRAM_TRACKING_RATE_LIMIT_WINDOW_SECONDS=60,
)
class TelegramCustomerRateLimitTests(TelegramIntegrationBaseTests):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_fourth_bot_lookup_from_same_telegram_identity_is_rate_limited(self):
        for update_id in range(2010, 2013):
            ingest_and_process_telegram_update(
                update=self.message_update(
                    update_id=update_id,
                    text="/track OAL-unknown-code",
                    telegram_user_id=820010,
                    telegram_chat_id=820010,
                )
            )

        ingest_and_process_telegram_update(
            update=self.message_update(
                update_id=2013,
                text="/track OAL-unknown-code",
                telegram_user_id=820010,
                telegram_chat_id=820010,
            )
        )

        blocked_reply = TelegramOutboxMessage.objects.get(
            inbound_update__telegram_update_id=2013,
        )
        self.assertEqual(blocked_reply.message_type, "customer_tracking_rate_limited")
        self.assertIn("بیش از حد مجاز", blocked_reply.body)


class CustomerTrackingNotificationTests(TelegramIntegrationBaseTests):
    def test_stage_confirmation_creates_one_customer_notification_and_outbox_message(self):
        issued_code = self.issue_customer_activation_code()
        subscription = activate_customer_telegram_tracking(
            code=issued_code["code"],
            telegram_user_id=830001,
            telegram_chat_id=830001,
        )

        confirm_stage(
            car=self.car,
            stage=self.clearance_stage,
            staff=self.clearance_employee,
        )

        notification = CustomerTrackingNotification.objects.get(
            subscription=subscription,
            tracking_event__event_type=TrackingEvent.EventType.STAGE_CONFIRMED,
        )

        self.assertEqual(notification.outbox_message.customer_subscription, subscription)
        self.assertEqual(
            notification.outbox_message.message_type,
            "customer_tracking_notification",
        )
        self.assertIn(self.clearance_stage.name, notification.outbox_message.body)

    def test_unsubscribed_customer_receives_no_future_tracking_notifications(self):
        issued_code = self.issue_customer_activation_code()
        activate_customer_telegram_tracking(
            code=issued_code["code"],
            telegram_user_id=830002,
            telegram_chat_id=830002,
        )
        unsubscribe_customer_telegram_tracking(
            tracking_code=self.car.tracking_code,
            telegram_user_id=830002,
            telegram_chat_id=830002,
        )

        confirm_stage(
            car=self.car,
            stage=self.clearance_stage,
            staff=self.clearance_employee,
        )

        self.assertFalse(CustomerTrackingNotification.objects.exists())


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


class TelegramOutboxAdministrativeRecoveryTests(TestCase):
    def setUp(self):
        self.administrator = get_user_model().objects.create_superuser(
            username="telegram-retry-administrator",
            password="test-password",
        )
        self.outbox_message = TelegramOutboxMessage.objects.create(
            operation=TelegramOutboxMessage.Operation.SEND_MESSAGE,
            chat_id=700001,
            body="پیام ناموفق",
            message_type="test_failure",
            idempotency_key="telegram-admin-retry-test",
            status=TelegramOutboxMessage.Status.FAILED,
            attempt_count=6,
            last_error_summary="خطای آزمایشی",
        )

    def test_system_administrator_can_requeue_a_failed_outbox_message(self):
        result = retry_failed_telegram_outbox_message(
            outbox_id=self.outbox_message.pk,
            actor=self.administrator,
        )

        result.refresh_from_db()
        self.assertEqual(result.status, TelegramOutboxMessage.Status.PENDING)
        self.assertEqual(result.last_error_summary, "")
        self.assertEqual(result.attempt_count, 6)
