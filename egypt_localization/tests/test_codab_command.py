from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from egypt_localization.management.commands.import_codab_locations import Command, _codab_location_service_class


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

        class BaseService:
            scope_writes = []
            calls = []

            def __init__(self, operator):
                self.operator = operator

            def _ensure_user_belongs_to_district(self, *args, **kwargs):
                type(self).scope_writes.append((args, kwargs))

            def update_or_create(self, data):
                type(self).calls.append(data)
                self._ensure_user_belongs_to_district(data)

        BaseService.scope_writes = []
        BaseService.calls = []
        self.service_class = _codab_location_service_class(BaseService)

    def test_apply_uses_real_one_argument_service_and_parent_uuid(self):
        with patch('egypt_localization.management.commands.import_codab_locations.transaction.atomic') as atomic, \
             patch.object(Command, '_location_service_class', return_value=self.service_class) as factory:
            atomic.return_value.__enter__.return_value = None
            Command._apply([self.row], self.diff, self.model, self.user)
            factory.assert_called_once_with()
            self.assertEqual(self.service_class.__name__, 'CodabLocationService')
            self.assertEqual(self.service_class.calls[0]['parent_uuid'], 'r-uuid')
            self.assertNotIn('parent_id', self.service_class.calls[0])
            self.assertNotIn('parent', self.service_class.calls[0])
            self.assertEqual(self.service_class.calls[0]['json_ext']['healthpay_issue37_codab']['source_fields'], self.row['source_fields'])
            self.assertEqual(self.service_class.scope_writes, [])
            self.manager.create.assert_not_called()

    def test_skip_never_calls_service(self):
        with patch('egypt_localization.management.commands.import_codab_locations.transaction.atomic'), \
             patch.object(Command, '_location_service_class', return_value=self.service_class):
            Command._apply([self.row], {'decisions': [{'code': 'EG0109', 'outcome': 'skip'}]}, self.model, self.user)
            self.assertEqual(self.service_class.calls, [])
            self.assertEqual(self.service_class.scope_writes, [])

    def test_concurrent_code_collision_aborts_before_service(self):
        self.manager.filter.return_value.exists.return_value = True
        with patch('egypt_localization.management.commands.import_codab_locations.transaction.atomic'), \
             patch.object(Command, '_location_service_class', return_value=self.service_class):
            with self.assertRaisesRegex(CommandError, 'concurrent code collision'):
                Command._apply([self.row], self.diff, self.model, self.user)
            self.assertEqual(self.service_class.calls, [])
            self.assertEqual(self.service_class.scope_writes, [])

    def test_missing_parent_aborts_before_service(self):
        self.manager.filter.return_value.first.return_value = None
        with patch('egypt_localization.management.commands.import_codab_locations.transaction.atomic'), \
             patch.object(Command, '_location_service_class', return_value=self.service_class):
            with self.assertRaisesRegex(CommandError, 'parent .* missing'):
                Command._apply([self.row], self.diff, self.model, self.user)
            self.assertEqual(self.service_class.calls, [])
            self.assertEqual(self.service_class.scope_writes, [])
