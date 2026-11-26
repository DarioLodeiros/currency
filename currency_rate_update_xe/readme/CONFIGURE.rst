Now you can choose the 'XE.com' service when configuring
a currency rates providers.

#. Go to *Invoicing > Configuration > Currency Rates Providers*.
#. Create a new 'Currency Rates Providers' or edit an existing
   one and you will see 'XE.com' among the available
   'Source Services' to choose.
#. If you choose 'XE.com' as a 'Source Service', the exchange rates
   will be updated from that provider.

XE.com only provides the current rates, so:

* Set the provider as daily, so that the scheduled action stores the rate
  of every day. Days without a successful run are left without a rate.
* The *Update Rates* wizard refuses past dates when an XE.com provider is
  selected.
