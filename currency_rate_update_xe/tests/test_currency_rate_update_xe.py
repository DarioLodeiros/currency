# Copyright 2023 Tecnativa - Ernesto Tejeda
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import json
from datetime import timedelta
from unittest import mock

import requests
from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import common

XE_PAYLOAD = {
    "timestamp": 1795523400000,
    "rates": {
        "USD": 1.0,
        "EUR": 0.9124972795,
        "AED": 3.6725,
        "SAR": 3.75,
    },
}
FROZEN_NOW = "2026-11-24 10:00:00"
FAILURE_SUBJECT = "Currency Rate Provider Failure"


class TestResCurrencyRateProviderXE(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.CurrencyRate = cls.env["res.currency.rate"]
        cls.eur_currency = cls.env.ref("base.EUR")
        cls.aed_currency = cls.env.ref("base.AED")
        cls.sar_currency = cls.env.ref("base.SAR")
        (cls.aed_currency | cls.sar_currency).write({"active": True})
        cls.company = cls.env["res.company"].create(
            {"name": "Test company", "currency_id": cls.eur_currency.id}
        )
        cls.env.user.company_ids += cls.company
        cls.env.company = cls.company
        cls.xe_provider = cls.env["res.currency.rate.provider"].create(
            {
                "service": "XE",
                "company_id": cls.company.id,
                "currency_ids": [
                    (6, 0, (cls.aed_currency | cls.sar_currency).ids),
                ],
            }
        )

    def setUp(self):
        super().setUp()
        self.status_code = 200
        self.content = json.dumps(XE_PAYLOAD).encode()
        patcher = mock.patch.object(requests, "get", side_effect=self._fake_xe_get)
        self.get_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def _fake_xe_get(self, url, **kwargs):
        response = requests.Response()
        response.status_code = self.status_code
        response.url = url
        response._content = self.content
        return response

    def _provider_rates(self):
        return self.CurrencyRate.search(
            [
                ("company_id", "=", self.company.id),
                ("currency_id", "in", (self.aed_currency | self.sar_currency).ids),
            ]
        )

    def _failure_messages(self):
        return self.xe_provider.message_ids.filtered(
            lambda m: m.subject == FAILURE_SUBJECT
        )

    def _assert_failure_logged(self, text):
        messages = self._failure_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn(text, messages.body)

    def _new_wizard(self, date_from, date_to):
        return (
            self.env["res.currency.rate.update.wizard"]
            .with_context(default_provider_ids=[(6, False, self.xe_provider.ids)])
            .create({"date_from": date_from, "date_to": date_to})
        )

    @freeze_time(FROZEN_NOW)
    def test01_cron_saves_today_rates(self):
        today = fields.Date.today()
        self.assertTrue(self.xe_provider.daily)
        self.xe_provider._scheduled_update()
        rates = self._provider_rates()
        self.assertEqual(
            rates.mapped("currency_id"), self.aed_currency | self.sar_currency
        )
        self.assertEqual(set(rates.mapped("name")), {today})
        self.assertEqual(self.xe_provider.last_successful_run, today)

    @freeze_time(FROZEN_NOW)
    def test02_rates_relative_to_company_currency(self):
        self.xe_provider._scheduled_update()
        rates = self._provider_rates()
        aed = rates.filtered(lambda r: r.currency_id == self.aed_currency)
        sar = rates.filtered(lambda r: r.currency_id == self.sar_currency)
        self.assertEqual(len(aed), 1)
        self.assertEqual(len(sar), 1)
        self.assertAlmostEqual(aed.rate, 3.6725 / 0.9124972795, places=4)
        self.assertAlmostEqual(sar.rate, 3.75 / 0.9124972795, places=4)

    @freeze_time(FROZEN_NOW)
    def test03_http_error_logs_failure(self):
        known_date = fields.Date.today() - timedelta(days=4)
        self.xe_provider.last_successful_run = known_date
        self.status_code = 403
        self.xe_provider._scheduled_update()
        self._assert_failure_logged("HTTP 403")
        self.assertEqual(self.xe_provider.last_successful_run, known_date)
        self.assertFalse(self._provider_rates())

    @freeze_time(FROZEN_NOW)
    def test04_missing_currencies_logs_failure(self):
        known_date = fields.Date.today() - timedelta(days=4)
        self.xe_provider.last_successful_run = known_date
        self.content = json.dumps({"rates": {"USD": 1.0, "EUR": 0.9124972795}}).encode()
        self.xe_provider._scheduled_update()
        self._assert_failure_logged("AED, SAR")
        self.assertEqual(self.xe_provider.last_successful_run, known_date)
        self.assertFalse(self._provider_rates())

    @freeze_time(FROZEN_NOW)
    def test05_wizard_past_dates_raises(self):
        today = fields.Date.today()
        wizard = self._new_wizard(today - timedelta(days=1), today)
        with self.assertRaisesRegex(UserError, "only provides today"):
            wizard.action_update()
        self.assertFalse(self._provider_rates())
        self.get_mock.assert_not_called()

    @freeze_time(FROZEN_NOW)
    def test06_wizard_today_saves_rates(self):
        today = fields.Date.today()
        wizard = self._new_wizard(today, today)
        wizard.action_update()
        rates = self._provider_rates()
        self.assertEqual(
            rates.mapped("currency_id"), self.aed_currency | self.sar_currency
        )
        self.assertEqual(set(rates.mapped("name")), {today})

    @freeze_time(FROZEN_NOW)
    def test07_overdue_non_daily_provider(self):
        today = fields.Date.today()
        self.xe_provider.write(
            {
                "interval_type": "weeks",
                "interval_number": 1,
                "next_run": today - timedelta(days=10),
                "last_successful_run": today - timedelta(days=17),
            }
        )
        self.assertFalse(self.xe_provider.daily)
        self.xe_provider._scheduled_update()
        rates = self._provider_rates()
        self.assertEqual(
            rates.mapped("currency_id"), self.aed_currency | self.sar_currency
        )
        self.assertEqual(set(rates.mapped("name")), {today})
        self.assertFalse(self._failure_messages())
        self.assertEqual(self.xe_provider.last_successful_run, today)
        self.assertEqual(self.xe_provider.next_run, today + timedelta(weeks=1))

    @freeze_time(FROZEN_NOW)
    def test08_request_headers(self):
        today = fields.Date.today()
        self.xe_provider._obtain_rates("EUR", ["AED"], today, today)
        self.get_mock.assert_called_once()
        headers = self.get_mock.call_args.kwargs["headers"]
        self.assertTrue(headers["Authorization"].startswith("Basic "))
        self.assertIn("Mozilla", headers["User-Agent"])

    @freeze_time(FROZEN_NOW)
    def test09_invalid_json_raises(self):
        today = fields.Date.today()
        self.content = b"<html>not json</html>"
        with self.assertRaisesRegex(UserError, "Couldn't fetch data"):
            self.xe_provider._obtain_rates("EUR", ["AED"], today, today)

    @freeze_time(FROZEN_NOW)
    def test10_missing_base_currency_raises(self):
        today = fields.Date.today()
        self.content = json.dumps({"rates": {"USD": 1.0, "AED": 3.6725}}).encode()
        with self.assertRaisesRegex(UserError, "base currency EUR"):
            self.xe_provider._obtain_rates("EUR", ["AED"], today, today)

    @freeze_time(FROZEN_NOW)
    def test11_partial_missing_currency_logs_failure(self):
        known_date = fields.Date.today() - timedelta(days=4)
        self.xe_provider.last_successful_run = known_date
        payload = {"rates": dict(XE_PAYLOAD["rates"])}
        del payload["rates"]["SAR"]
        self.content = json.dumps(payload).encode()
        self.xe_provider._scheduled_update()
        self._assert_failure_logged("SAR")
        self.assertNotIn("AED", self._failure_messages().body)
        self.assertEqual(self.xe_provider.last_successful_run, known_date)
        self.assertFalse(self._provider_rates())

    @freeze_time(FROZEN_NOW)
    def test12_wizard_past_dates_other_provider(self):
        today = fields.Date.today()
        Provider = self.env["res.currency.rate.provider"]
        ecb_provider = Provider.create(
            {
                "service": "ECB",
                "company_id": self.company.id,
                "currency_ids": [(6, 0, self.env.ref("base.USD").ids)],
            }
        )
        wizard = (
            self.env["res.currency.rate.update.wizard"]
            .with_context(default_provider_ids=[(6, False, ecb_provider.ids)])
            .create({"date_from": today - timedelta(days=1), "date_to": today})
        )
        with mock.patch.object(type(Provider), "_update") as update_mock:
            wizard.action_update()
        update_mock.assert_called_once()
