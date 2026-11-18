import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type Members = components["schemas"]["MembersOut"];
export type Member = components["schemas"]["MemberOut"];
export type Invite = components["schemas"]["InviteOut"];
export type InvitePreview = components["schemas"]["InvitePreviewOut"];
export type InviteRole = components["schemas"]["InviteIn"]["role"];
export type Role = "owner" | "admin" | "billing" | "ca";

export const membersKey = (businessId: string) => ["b", businessId, "members"] as const;

/** Who is on the team and which invitations are open. Owner and admin only; anyone else gets the not-found page. */
export function useMembers(businessId: string, enabled: boolean) {
  return useQuery<Members, ApiError>({
    queryKey: membersKey(businessId),
    enabled: enabled && Boolean(businessId),
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/members", { params: { path: { business_id: businessId } } })),
  });
}

function useRefresh(businessId: string) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: membersKey(businessId) });
}

/** Sends the invitation by email only. The link is never shown here. One key per form fill, so a retry sends one mail. */
export function useInvite(businessId: string) {
  const refresh = useRefresh(businessId);
  return useMutation<Invite, ApiError, { email: string; role: InviteRole; display_name?: string; key: string }>({
    mutationFn: ({ key, ...body }) =>
      call(() => api.POST("/api/v1/b/{business_id}/invitations", { params: { path: { business_id: businessId }, header: { "idempotency-key": key } }, body })),
    onSuccess: refresh,
  });
}

export function useResend(businessId: string) {
  const refresh = useRefresh(businessId);
  return useMutation<Invite, ApiError, string>({
    mutationFn: (id) => call(() => api.POST("/api/v1/b/{business_id}/invitations/{invitation_id}/resend", { params: { path: { business_id: businessId, invitation_id: id } } })),
    onSuccess: refresh,
  });
}

export function useCancelInvite(businessId: string) {
  const refresh = useRefresh(businessId);
  return useMutation<Invite, ApiError, string>({
    mutationFn: (id) => call(() => api.POST("/api/v1/b/{business_id}/invitations/{invitation_id}/cancel", { params: { path: { business_id: businessId, invitation_id: id } } })),
    onSuccess: refresh,
  });
}

export function useChangeRole(businessId: string) {
  const refresh = useRefresh(businessId);
  return useMutation<Member, ApiError, { userId: string; role: Role }>({
    mutationFn: ({ userId, role }) => call(() => api.PATCH("/api/v1/b/{business_id}/members/{user_id}", { params: { path: { business_id: businessId, user_id: userId } }, body: { role } })),
    onSuccess: refresh,
    onError: refresh, // the list may have moved under the person: show it as it is
  });
}

export function useSetActive(businessId: string) {
  const refresh = useRefresh(businessId);
  return useMutation<Member, ApiError, { userId: string; active: boolean; reason: string }>({
    mutationFn: ({ userId, active, reason }) =>
      call(() =>
        api.POST(active ? "/api/v1/b/{business_id}/members/{user_id}/reactivate" : "/api/v1/b/{business_id}/members/{user_id}/deactivate", {
          params: { path: { business_id: businessId, user_id: userId } },
          body: { reason },
        }),
      ),
    onSuccess: refresh,
    onError: refresh,
  });
}

/** What the invitation is, for the person it was sent to (matched on their signed-in email). */
export function useInvitePreview(token: string, enabled: boolean) {
  return useQuery<InvitePreview, ApiError>({
    queryKey: ["invitation", token],
    enabled: enabled && Boolean(token),
    retry: false,
    gcTime: 0,
    queryFn: () => call(() => api.GET("/api/v1/me/invitations/{token}", { params: { path: { token } } })),
  });
}

export function useAcceptInvite(token: string) {
  return useMutation<components["schemas"]["AcceptOut"], ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/me/invitations/{token}/accept", { params: { path: { token } } })),
  });
}
