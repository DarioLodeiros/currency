# Copyright 2026 FactorLibre - Ivan Bosquez
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResCurrencyRateUpdateWizard(models.TransientModel):
    _inherit = "res.currency.rate.update.wizard"

    def action_update(self):
        self.ensure_one()
        if self.date_from < fields.Date.context_today(self) and "XE" in (
            self.provider_ids.mapped("service")
        ):
            raise UserError(
                _(
                    "XE.com only provides today's rates, so rates for past dates "
                    "can't be obtained. Remove the XE.com provider or use today's "
                    "date."
                )
            )
        return super().action_update()
