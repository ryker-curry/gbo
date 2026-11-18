// GBO -- whoop-oauth-callback Edge Function (Oct 2026 WHOOP pilot).
//
// This URL is the Redirect URI registered in the WHOOP Developer Dashboard:
//   https://zjqwirsxofosungqoyau.supabase.co/functions/v1/whoop-oauth-callback
//
//   ?connect=<state>      the "Connect WHOOP" link GBO hands the player.
//                         Checks the link, then sends him to WHOOP's sign-in.
//   ?code=...&state=...   WHOOP sends him back here after he taps Allow.
//                         Trades the code for tokens, stores them encrypted,
//                         pulls the last 90 days, shows a "you're connected" page.
//   ?error=...            he tapped Deny (or WHOOP had a problem).
//
// Deployed with verify_jwt = false (a browser redirect carries no Supabase
// JWT); the one-time state value is what authorizes each step.

import { BACKFILL_DAYS, SCOPES, WHOOP_AUTH_URL, callbackUrl, db, env, exchangeCode, saveTokens, syncPlayer, whoopGet } from "../_shared/whoop.ts";

// Plain text on purpose: Supabase serves Edge Function responses on the
// default *.supabase.co domain as text/plain (HTML would show as raw tags),
// so the player gets a short readable message instead of a styled page.
function page(title: string, message: string, ok = true): Response {
  const text = `GORILLA BASEBALL OPERATIONS\n\n${title}\n\n${message}\n`;
  return new Response(text, { status: ok ? 200 : 400, headers: { "Content-Type": "text/plain; charset=utf-8" } });
}

const esc = (s: string) => s;  // plain-text responses, nothing to escape

async function validLink(sb: ReturnType<typeof db>, state: string) {
  const { data } = await sb.from("whoop_connect_links").select("*").eq("state", state).maybeSingle();
  if (!data) return { link: null, why: "This link isn't valid. Ask your coach for a new Connect WHOOP link." };
  if (data.used_at) return { link: null, why: "This link was already used. Ask your coach for a new one if you need to reconnect." };
  if (new Date(data.expires_at + "Z").getTime() < Date.now()) return { link: null, why: "This link expired. Ask your coach for a new one." };
  return { link: data, why: "" };
}

Deno.serve(async (req: Request) => {
  const url = new URL(req.url);
  const sb = db();
  try {
    const connect = url.searchParams.get("connect");
    if (connect) {
      const { link, why } = await validLink(sb, connect);
      if (!link) return page("Link not valid", why, false);
      const auth = new URL(WHOOP_AUTH_URL);
      auth.searchParams.set("client_id", env("WHOOP_CLIENT_ID"));
      auth.searchParams.set("redirect_uri", callbackUrl());
      auth.searchParams.set("response_type", "code");
      auth.searchParams.set("scope", SCOPES);
      auth.searchParams.set("state", connect);
      return Response.redirect(auth.toString(), 302);
    }

    const err = url.searchParams.get("error");
    if (err) {
      const desc = url.searchParams.get("error_description") ?? err;
      return page("Not connected", `WHOOP didn't connect (${esc(desc)}). If you meant to connect, open the link again and tap Allow.`, false);
    }

    const code = url.searchParams.get("code");
    const state = url.searchParams.get("state");
    if (!code || !state) return page("GBO WHOOP", "Open the Connect WHOOP link your coach sent you to get started.", false);

    const { link, why } = await validLink(sb, state);
    if (!link) return page("Link not valid", why, false);
    const playerId = Number(link.player_id);

    const tokens = await exchangeCode(code);
    await saveTokens(sb, playerId, tokens);
    let whoopUserId: number | null = null, whoopName: string | null = null;
    try {
      const prof = await whoopGet(tokens.access_token, "/v2/user/profile/basic");
      whoopUserId = prof.user_id ?? null;
      whoopName = [prof.first_name, prof.last_name].filter(Boolean).join(" ") || null;
    } catch (_) { /* profile is nice-to-have */ }
    const now = new Date().toISOString();
    const { error } = await sb.from("whoop_connections").upsert({
      player_id: playerId, whoop_user_id: whoopUserId, whoop_name: whoopName, scopes: tokens.scope ?? SCOPES,
      status: "connected", last_error: null, connected_at: now, last_synced_at: null, active: true, updated_at: now,
    }, { onConflict: "player_id" });
    if (error) throw new Error(`Saving connection failed: ${error.message}`);
    await sb.from("whoop_connect_links").update({ used_at: now }).eq("link_id", link.link_id);

    const result = await syncPlayer(sb, playerId, BACKFILL_DAYS);
    const first = whoopName ? esc(whoopName.split(" ")[0]) + ", y" : "Y";
    const detail = result.ok
      ? `We pulled ${result.days} days of WHOOP history. It updates automatically every morning and afternoon.`
      : "Your account is linked. The first data pull hit a snag, but it will try again on the next scheduled sync.";
    return page("WHOOP connected", `${first}our WHOOP is now linked to GBO. ${detail} You can close this page.`);
  } catch (e) {
    console.error(e);
    return page("Something went wrong", "GBO couldn't finish connecting WHOOP. Send your coach a screenshot of this page. (" +
      esc((e instanceof Error ? e.message : String(e)).slice(0, 200)) + ")", false);
  }
});
