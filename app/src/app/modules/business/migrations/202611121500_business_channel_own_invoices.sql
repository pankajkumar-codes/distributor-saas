-- ON-2 (BRD v1.2): "own sales invoices" is a fourth thing a business can say it has, beside
-- Amazon, Flipkart and Meesho. It is stored as one more row in marketplace_channels. The
-- column keeps its name (it is not renamed, to leave the RLS and grants alone) even though
-- own invoices are not a marketplace.
--
-- Widens the CHECK only: every existing row stays valid and no data is touched.

alter table business.marketplace_channels drop constraint marketplace_channels_marketplace_check;
alter table business.marketplace_channels
    add constraint marketplace_channels_marketplace_check
    check (marketplace in ('amazon', 'flipkart', 'meesho', 'own_invoices'));
