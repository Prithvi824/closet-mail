/** Builds the pre-filled "request an invite" email that the landing page's invite buttons open. */

import { SITE } from "./site";

export const INVITE_SUBJECT = "closet-mail invite request";

/**
 * The fields a requester fills in. The invite is sent to the inbox they name, and that inbox
 * becomes their first verified forwarding address; they pick a username when accepting it.
 */
export const INVITE_BODY = [
  "Hi,",
  "",
  "I'd like an invite to closet-mail.",
  "",
  "Name:",
  "Inbox to send the invite to (where my aliases will forward; leave blank to use this address):",
  "Where you found closet-mail (LinkedIn, my resume, GitHub, a friend):",
  "",
  "Thanks!",
].join("\n");

/**
 * Build a mailto: link with the subject and body already filled in.
 *
 * Args:
 *   to: Recipient address; defaults to the site's invite address.
 * Returns:
 *   The mailto: URL, with subject and body percent-encoded (RFC 6068).
 */
export function inviteMailto(to: string = SITE.inviteEmail): string {
  const query = `subject=${encodeURIComponent(INVITE_SUBJECT)}&body=${encodeURIComponent(INVITE_BODY)}`;
  return `mailto:${to}?${query}`;
}
