import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";

import { RequireAuth } from "./auth/AuthProvider";
import { NotFound } from "./kit/NotFound";
import { BusinessesPage } from "./screens/businesses/BusinessesPage";
import { HomePage } from "./screens/home/HomePage";
import { BusinessPage } from "./screens/onboarding/BusinessPage";
import { CustomerPage } from "./screens/customers/CustomerPage";
import { CustomersPage } from "./screens/customers/CustomersPage";
import { ImportPage } from "./screens/products/ImportPage";
import { ProductPage } from "./screens/products/ProductPage";
import { ProductsPage } from "./screens/products/ProductsPage";
import { SigninPage } from "./screens/signin/SigninPage";
import { SignupPage } from "./screens/signup/SignupPage";

// LLD-1 §11.2. Reset and Settings come in later S1 PRs.
export const routes: RouteObject[] = [
  { path: "/", element: <Navigate to="/signin" replace /> },
  { path: "/signup", element: <SignupPage /> },
  { path: "/signin", element: <SigninPage /> },
  { path: "/onboarding/business", element: <RequireAuth><BusinessPage /></RequireAuth> },
  { path: "/businesses", element: <RequireAuth><BusinessesPage /></RequireAuth> },
  { path: "/b/:businessId/home", element: <RequireAuth><HomePage /></RequireAuth> },
  { path: "/b/:businessId/customers", element: <RequireAuth><CustomersPage /></RequireAuth> },
  { path: "/b/:businessId/customers/new", element: <RequireAuth><CustomerPage /></RequireAuth> },
  { path: "/b/:businessId/customers/:customerId", element: <RequireAuth><CustomerPage /></RequireAuth> },
  { path: "/b/:businessId/products", element: <RequireAuth><ProductsPage /></RequireAuth> },
  { path: "/b/:businessId/products/import", element: <RequireAuth><ImportPage /></RequireAuth> },
  { path: "/b/:businessId/products/new", element: <RequireAuth><ProductPage /></RequireAuth> },
  { path: "/b/:businessId/products/:productId", element: <RequireAuth><ProductPage /></RequireAuth> },
  { path: "*", element: <NotFound /> },
];
