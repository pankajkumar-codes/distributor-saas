import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";

import { FEATURES } from "./features";
import { RequireAuth } from "./auth/AuthProvider";
import { PageTitle } from "./kit/PageTitle";
import { NotFound } from "./kit/NotFound";
import { BusinessesPage } from "./screens/businesses/BusinessesPage";
import { FilingHomePage } from "./screens/filing/FilingHomePage";
import { ReturnPage } from "./screens/filing/ReturnPage";
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
  { path: "/signup", element: <PageTitle title="Create your account"><SignupPage /></PageTitle> },
  { path: "/signin", element: <PageTitle title="Sign in"><SigninPage /></PageTitle> },
  { path: "/reset", element: <PageTitle title="Reset your password"><ResetPage /></PageTitle> },
  { path: "/onboarding/business", element: <PageTitle title="Set up your business"><RequireAuth><BusinessPage /></RequireAuth></PageTitle> },
  { path: "/businesses", element: <PageTitle title="Your businesses"><RequireAuth><BusinessesPage /></RequireAuth></PageTitle> },
  { path: "/support", element: <PageTitle title="Support"><RequireAuth><SupportBusinessesPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/home", element: <PageTitle title="Home"><RequireAuth><HomePage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/filing", element: <PageTitle title="Your GST filing"><RequireAuth><FilingHomePage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/filing/:instanceId", element: <PageTitle title="Your return"><RequireAuth><ReturnPage /></RequireAuth></PageTitle> },
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
  { path: "/b/:businessId/settings/company", element: <PageTitle title="Business details"><RequireAuth><CompanyPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/settings/filing", element: <PageTitle title="Filing frequency"><RequireAuth><FilingPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/settings/support", element: <PageTitle title="Support access"><RequireAuth><SupportPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/settings/audit", element: <PageTitle title="Audit log"><RequireAuth><AuditPage /></RequireAuth></PageTitle> },
  { path: "/b/:businessId/settings/security", element: <PageTitle title="Two-step sign-in"><RequireAuth><SecurityPage /></RequireAuth></PageTitle> },
  { path: "/account/security", element: <PageTitle title="Two-step sign-in"><RequireAuth><SecurityPage /></RequireAuth></PageTitle> },
  { path: "/support/totp-recovery", element: <PageTitle title="Recover two-step sign-in"><RequireAuth><TotpRecoveryPage /></RequireAuth></PageTitle> },
  { path: "*", element: <PageTitle title="Page not found"><NotFound /></PageTitle> },
];
