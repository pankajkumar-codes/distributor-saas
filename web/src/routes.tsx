import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";

import { NotFound } from "./kit/NotFound";
import { BusinessPlaceholder } from "./screens/onboarding/BusinessPlaceholder";
import { SignupPage } from "./screens/signup/SignupPage";

// LLD-1 §11.2. Sign-in, reset, Home and Settings come in later S1 PRs.
export const routes: RouteObject[] = [
  { path: "/", element: <Navigate to="/signup" replace /> },
  { path: "/signup", element: <SignupPage /> },
  { path: "/onboarding/business", element: <BusinessPlaceholder /> },
  { path: "*", element: <NotFound /> },
];
