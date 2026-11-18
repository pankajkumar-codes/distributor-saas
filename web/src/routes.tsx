import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";

import { FEATURES } from "./features";
import { RequireAuth } from "./auth/AuthProvider";
import { PageTitle } from "./kit/PageTitle";
import { NotFound } from "./kit/NotFound";
import { BusinessesPage } from "./screens/businesses/BusinessesPage";
import { FilingHomePage } from "./screens/filing/FilingHomePage";
import { Portal3bGuidePage } from "./screens/filing/Portal3bGuidePage";
import { WorksheetPage } from "./screens/filing/WorksheetPage";
import { ReturnPage } from "./screens/filing/ReturnPage";
import { UploadsPage } from "./screens/uploads/UploadsPage";
import { CrosscheckPage } from "./screens/uploads/CrosscheckPage";
import { HomePage } from "./screens/home/HomePage";
import { BusinessPage } from "./screens/onboarding/BusinessPage";
import { CustomerPage } from "./screens/customers/CustomerPage";
import { CustomersPage } from "./screens/customers/CustomersPage";
import { InvoicePage } from "./screens/invoices/InvoicePage";
import { ImportPage } from "./screens/products/ImportPage";
import { ProductPage } from "./screens/products/ProductPage";
import { ProductsPage } from "./screens/products/ProductsPage";
import { ResetPage } from "./screens/reset/ResetPage";
import { SettingsPage, ToBusinessSetup } from "./screens/settings/SettingsPage";
import { AuditPage } from "./screens/settings/AuditPage";
import { SecurityPage } from "./screens/settings/SecurityPage";
import { MarketplacesPage } from "./screens/settings/MarketplacesPage";
import { SupportPage } from "./screens/settings/SupportPage";
import { SigninPage } from "./screens/signin/SigninPage";
import { SupportBusinessesPage } from "./screens/support/SupportBusinessesPage";
import { TotpRecoveryPage } from "./screens/support/TotpRecoveryPage";
import { SignupPage } from "./screens/signup/SignupPage";

// LLD-1 §11.2. Team and My account come in later S1 PRs.
export const routes: RouteObject[] = [
  { path: "/", element: <Navigate to="/signin" replace /> },
  { path: "/signup", element: <PageTitle title="Create your account"><SignupPage /></PageTitle> },
  { path: "/signin", element: <PageTitle title="Sign in"><SigninPage /></PageTitle> },
  { path: "/reset", element: <PageTitle title="Reset your password"><ResetPage /></PageTitle> },
  { path: "/onboarding/business", element: <PageTitle title="Set up your business"><RequireAuth><BusinessPage /></RequireAuth></PageTitle> },
  { path: "/businesses", element: <PageTitle title="Your businesses"><RequireAuth><BusinessesPage /></RequireAuth></PageTitle> },
  { path: "/support", element: <PageTitle title="Support"><RequireAuth><SupportBusinessesPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/home", element: <PageTitle title="Home"><RequireAuth><HomePage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/filing", element: <PageTitle title="Your GST filing"><RequireAuth><FilingHomePage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/filing/:instanceId/worksheet", element: <PageTitle title="GSTR-3B worksheet"><RequireAuth><WorksheetPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/filing/:instanceId", element: <PageTitle title="Your return"><RequireAuth><ReturnPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/filing/:instanceId/portal-guide-3b", element: <PageTitle title="Enter GSTR-3B on the GST portal"><RequireAuth><Portal3bGuidePage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/uploads/crosscheck", element: <PageTitle title="Cross-check"><RequireAuth><CrosscheckPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/uploads", element: <PageTitle title="Upload your reports"><RequireAuth><UploadsPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/customers", element: <PageTitle title="Customers"><RequireAuth><CustomersPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/customers/new", element: <PageTitle title="New customer"><RequireAuth><CustomerPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/customers/:customerId", element: <PageTitle title="Customer"><RequireAuth><CustomerPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/products", element: <PageTitle title="Products"><RequireAuth><ProductsPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/products/import", element: <PageTitle title="Import products"><RequireAuth><ImportPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/products/new", element: <PageTitle title="New product"><RequireAuth><ProductPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/products/:productId", element: <PageTitle title="Product"><RequireAuth><ProductPage /></RequireAuth></PageTitle> },
  ...(FEATURES.invoicing
    ? [
        { path: "/b/:businessId/invoices/new", element: <PageTitle title="New invoice"><RequireAuth><InvoicePage /></RequireAuth></PageTitle> },
        { path: "/b/:businessId/invoices/:draftId", element: <PageTitle title="Invoice"><RequireAuth><InvoicePage /></RequireAuth></PageTitle> },
      ]
    : []),
  { path: "/b/:businessId/settings", element: <PageTitle title="Business setup"><RequireAuth><SettingsPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/settings/company", element: <RequireAuth><ToBusinessSetup /></RequireAuth> },
  { path: "/b/:businessId/onboarding/marketplaces", element: <PageTitle title="Marketplaces you sell on"><RequireAuth><MarketplacesPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/settings/filing", element: <RequireAuth><ToBusinessSetup /></RequireAuth> },
  { path: "/b/:businessId/settings/support", element: <PageTitle title="Support access"><RequireAuth><SupportPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/settings/audit", element: <PageTitle title="Audit log"><RequireAuth><AuditPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/settings/security", element: <PageTitle title="Two-step sign-in"><RequireAuth><SecurityPage /></RequireAuth></PageTitle> },
  { path: "/account/security", element: <PageTitle title="Two-step sign-in"><RequireAuth><SecurityPage /></RequireAuth></PageTitle> },
  { path: "/support/totp-recovery", element: <PageTitle title="Recover two-step sign-in"><RequireAuth><TotpRecoveryPage /></RequireAuth></PageTitle> },
  { path: "*", element: <PageTitle title="Page not found"><NotFound /></PageTitle> },
];
