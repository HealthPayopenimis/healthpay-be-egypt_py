from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from egypt_localization.management.commands.import_codab_locations import Command


class CodabCommandTest(SimpleTestCase):
    def setUp(self):
        self.parent = SimpleNamespace(id=5, uuid='r-uuid')
        self.manager = MagicMock()
        self.manager.filter.return_value.first.return_value = self.parent
        self.manager.filter.return_value.exists.return_value = False
        self.model = SimpleNamespace(objects=self.manager, _base_manager=self.manager)
        self.user = SimpleNamespace(id=1, id_for_audit=1)
        self.row = {'code': 'EG0109', 'type': 'D', 'name': 'اختبار', 'parent_code': 'EG01',
                    'source_sheet': 'egy_admin2', 'source_fields': {'lang1': 'ar'}}
        self.diff = {'decisions': [{'code': 'EG0109', 'outcome': 'add'}]}

    def test_apply_uses_real_one_argument_service_and_parent_uuid(self):
        with patch('egypt_localization.management.commands.import_codab_locations.transaction.atomic') as atomic, \
             patch('location.services.LocationService') as service:
            atomic.return_value.__enter__.return_value = None
            Command._apply([self.row], self.diff, self.model, self.user)
            service.assert_called_once_with(self.user)
            args = service.return_value.update_or_create.call_args.args
            self.assertEqual(len(args), 1)
            self.assertEqual(args[0]['parent_uuid'], 'r-uuid')
            self.assertNotIn('parent_id', args[0])
            self.assertNotIn('parent', args[0])
            self.assertEqual(args[0]['json_ext']['healthpay_issue37_codab']['source_fields'], self.row['source_fields'])
            self.manager.create.assert_not_called()

    def test_skip_never_calls_service(self):
        with patch('egypt_localization.management.commands.import_codab_locations.transaction.atomic'), \
             patch('location.services.LocationService') as service:
            Command._apply([self.row], {'decisions': [{'code': 'EG0109', 'outcome': 'skip'}]}, self.model, self.user)
            service.return_value.update_or_create.assert_not_called()

    def test_concurrent_code_collision_aborts_before_service(self):
        self.manager.filter.return_value.exists.return_value = True
        with patch('egypt_localization.management.commands.import_codab_locations.transaction.atomic'), \
             patch('location.services.LocationService') as service:
            with self.assertRaisesRegex(CommandError, 'concurrent code collision'):
                Command._apply([self.row], self.diff, self.model, self.user)
            service.return_value.update_or_create.assert_not_called()

    def test_missing_parent_aborts_before_service(self):
        self.manager.filter.return_value.first.return_value = None
        with patch('egypt_localization.management.commands.import_codab_locations.transaction.atomic'), \
             patch('location.services.LocationService') as service:
            with self.assertRaisesRegex(CommandError, 'parent .* missing'):
                Command._apply([self.row], self.diff, self.model, self.user)
            service.return_value.update_or_create.assert_not_called()
