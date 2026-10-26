-- The reshape (202610251700) makes identity_auth the owner of identity's definer
-- functions. Only a superuser may hand a function to a role that lacks CREATE on its
-- schema, and the RDS master isn't one, so the reshape failed there. This file sorts
-- just before it; S0a (c2) revokes the right again once its own functions are owned.
grant create on schema identity to identity_auth;
