/* Connexion Microsoft depuis le téléphone (OAuth 2 avec PKCE, sans bibliothèque).
   Les jetons restent dans ce téléphone ; aucun mot de passe ne passe par PilotPro. */
const AUTH = (() => {
  const AUTORITE = "https://login.microsoftonline.com/consumers/oauth2/v2.0";
  const PORTEES = "openid profile offline_access https://graph.microsoft.com/Files.ReadWrite https://graph.microsoft.com/User.Read";
  const CLE = "pilotpro-jetons", CLE_FLUX = "pilotpro-flux";
  const retour = () => CONFIG.redirection || location.origin + location.pathname.replace(/index\.html$/, "");

  const lire = (cle) => { try { return JSON.parse(localStorage.getItem(cle) || "null"); } catch { return null; } };
  const ecrire = (cle, v) => { try { v === null ? localStorage.removeItem(cle) : localStorage.setItem(cle, JSON.stringify(v)); } catch { /* stockage indisponible */ } };

  const b64url = (octets) => btoa(String.fromCharCode(...new Uint8Array(octets))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const hasard = () => b64url(crypto.getRandomValues(new Uint8Array(32)));

  async function demanderJeton(champs) {
    const rep = await fetch(AUTORITE + "/token", {
      method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ client_id: CONFIG.client_id, scope: PORTEES, ...champs }),
    });
    const d = await rep.json().catch(() => ({}));
    if (!rep.ok) {
      const msg = d.error_description || "";
      if (msg.includes("AADSTS9002326") || msg.includes("Single-Page Application"))
        throw new Error("L'application Microsoft n'autorise pas encore le téléphone : ajoutez l'adresse de PilotPro mobile en « Application monopage » dans le portail Azure (voir le guide).");
      throw Object.assign(new Error("Connexion Microsoft refusée : " + (msg.split("\r\n")[0] || d.error || rep.status)), { reconnexion: true });
    }
    const j = { acces: d.access_token, renouvellement: d.refresh_token, expire: Date.now() + (d.expires_in - 300) * 1000 };
    ecrire(CLE, j);
    return j;
  }

  return {
    connecte: () => !!lire(CLE),

    async seConnecter() {
      const verificateur = hasard(), etat = hasard();
      const defi = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verificateur)));
      ecrire(CLE_FLUX, { verificateur, etat });
      location.href = AUTORITE + "/authorize?" + new URLSearchParams({
        client_id: CONFIG.client_id, response_type: "code", redirect_uri: retour(), response_mode: "query",
        scope: PORTEES, state: etat, code_challenge: defi, code_challenge_method: "S256",
      });
    },

    /* Au retour de la page Microsoft : échange le code contre les jetons. Renvoie true si c'était un retour. */
    async traiterRetour() {
      const p = new URLSearchParams(location.search);
      if (!p.has("code") && !p.has("error")) return false;
      history.replaceState(null, "", location.pathname);
      const flux = lire(CLE_FLUX);
      ecrire(CLE_FLUX, null);
      if (p.has("error")) throw new Error("Connexion annulée ou refusée : " + (p.get("error_description") || p.get("error")));
      if (!flux || flux.etat !== p.get("state")) throw new Error("Connexion interrompue : recommencez.");
      await demanderJeton({ grant_type: "authorization_code", code: p.get("code"), redirect_uri: retour(), code_verifier: flux.verificateur });
      return true;
    },

    /* Jeton d'accès valide, renouvelé si besoin. Lève une erreur « reconnexion » si la session a expiré. */
    async jeton() {
      const j = lire(CLE);
      if (!j) throw Object.assign(new Error("Connexion Microsoft requise."), { reconnexion: true });
      if (Date.now() < j.expire) return j.acces;
      try {
        return (await demanderJeton({ grant_type: "refresh_token", refresh_token: j.renouvellement })).acces;
      } catch (e) {
        if (e.reconnexion) ecrire(CLE, null);
        throw e;
      }
    },

    seDeconnecter() { ecrire(CLE, null); },
  };
})();
