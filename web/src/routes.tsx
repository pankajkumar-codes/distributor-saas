import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";

import { FEATURES } from "./features";
import { RequireAuth } from "./auth/AuthProvider";
import { NotFound } from "./kit/NotFound";
import { BusinessesPage } from "./screens/businesses/BusinessesPage";
import { FilingHomePage } from "./screens/filing/FilingHomePage";
import { UploadsPage } from "./screens/uploads/UploadsPage";
import { HomePage } from "./screens/home/HomePage";
import { BusinessPage } from "./screens/onboarding/BusinessPage";
import { CustomerPage } from "./screens/customers/CustomerPage";
import { CustomersPage } from "./screens/customers/CustomersPage";
import { InvoicePage } from "./screens/invoices/InvoicePage";
import { ImportPage } from "./screens/products/ImportPage";
import { ProductPage } from "./screens/products/ProductPage";
import { ProductsPage } from "./screens/products/ProductsPage";
import { ResetPage } from "./screens/reset/ResetPage";
import { AuditPage } from "./screens/settings/AuditPage";
import { SecurityPage } from "./screens/settings/SecurityPage";
import { CompanyPage } from "./screens/settings/CompanyPage";
import { FilingPage } from "./screens/settings/FilingPage";
import { SupportPage } from "./screens/settings/SupportPage";
import { SigninPage } from "./screens/signin/SigninPage";
import { SupportBusinessesPage } from "./screens/support/SupportBusinessesPage";
import { TotpRecoveryPage } from "./screens/support/TotpRecoveryPage";
import { SignupPage } from "./screens/signup/SignupPage";

// LLD-1 §11.2. Team and My account come in later S1 PRs.
export const routes: RouteObject[] = [
  { path: "/", element: <Navigate to="/signin" replace /> },
  { path: "/signup", element: <SignupPage /> },
  { path: "/signin", element: <SigninPage /> },
  { path: "/reset", element: <ResetPage /> },
  { path: "/onboarding/business", element: <RequireAuth><BusinessPage /></RequireAuth> },
  { path: "/businesses", element: <RequireAuth><BusinessesPage /></RequireAuth> },
  { path: "/support", element: <RequireAuth><SupportBusinessesPage /></RequireAuth> },
  { path: "/b/:businessId/home", element: <RequireAuth><HomePage /></RequireAuth> },
  { path: "/b/:businessId/filing", element: <RequireAuth><FilingHomePage /></RequireAuth> },
  { path: "/b/:businessId/uploads", element: <RequireAuth><UploadsPage /></RequireAuth> },
  { path: "/b/:businessId/customers", element: <RequireAuth><CustomersPage /></RequireAuth> },
  { path: "/b/:businessId/customers/new", element: <RequireAuth><CustomerPage /></RequireAuth> },
  { path: "/b/:businessId/customers/:customerId", element: <RequireAuth><CustomerPage /></RequireAuth> },
  { path: "/b/:businessId/products", element: <RequireAuth><ProductsPage /></RequireAuth> },
  { path: "/b/:businessId/products/import", element: <RequireAuth><ImportPage /></RequireAuth> },
  { path: "/b/:businessId/products/new", element: <RequireAuth><ProductPage /></RequireAuth> },
  { path: "/b/:businessId/products/:productId", element: <RequireAuth><ProductPage /></RequireAuth> },
  ...(FEATURES.invoicing
    ? [
        { path: "/b/:businessId/invoices/new", element: <RequireAuth><InvoicePage /></RequireAuth> },
        { path: "/b/:businessId/invoices/:draftId", element: <RequireAuth><InvoicePage /></RequireAuth> },
      ]
    : []),
  { path: "/b/:businessId/settings/company", element: <RequireAuth><CompanyPage /></RequireAuth> },
  { path: "/b/:businessId/settings/filing", element: <RequireAuth><FilingPage /></RequireAuth> },
  { path: "/b/:businessId/settings/support", element: <RequireAuth><SupportPage /></RequireAuth> },
  { path: "/b/:businessId/settings/audit", element: <RequireAuth><AuditPage /></RequireAuth> },
  { path: "/b/:businessId/settings/security", element: <RequireAuth><SecurityPage /></RequireAuth> },
  { path: "/account/security", element: <RequireAuth><SecurityPage /></RequireAuth> },
  { path: "/support/totp-recovery", element: <RequireAuth><TotpRecoveryPage /></RequireAuth> },
  { path: "*", element: <NotFound /> },
];
