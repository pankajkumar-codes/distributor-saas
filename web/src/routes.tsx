import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";

import { RequireAuth } from "./auth/AuthProvider";
import { NotFound } from "./kit/NotFound";
import { BusinessesPage } from "./screens/businesses/BusinessesPage";
import { HomePlaceholder } from "./screens/home/HomePlaceholder";
import { BusinessPage } from "./screens/onboarding/BusinessPage";
import { SigninPage } from "./screens/signin/SigninPage";
import { SignupPage } from "./screens/signup/SignupPage";

// LLD-1 §11.2. Reset, Settings and the real Home screen come in later S1 PRs.
export const routes: RouteObject[] = [
  { path: "/", element: <Navigate to="/signin" replace /> },
  { path: "/signup", element: <SignupPage /> },
  { path: "/signin", element: <SigninPage /> },
  { path: "/onboarding/business", element: <RequireAuth><BusinessPage /></RequireAuth> },
  { path: "/businesses", element: <RequireAuth><BusinessesPage /></RequireAuth> },
  { path: "/b/:businessId/home", element: <RequireAuth><HomePlaceholder /></RequireAuth> },
  { path: "*", element: <NotFound /> },
];
