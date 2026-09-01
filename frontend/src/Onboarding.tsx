import { useEffect, useState } from "react";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked";
import SyncIcon from "@mui/icons-material/Sync";
import VisibilityIcon from "@mui/icons-material/Visibility";
import VisibilityOffIcon from "@mui/icons-material/VisibilityOff";
import {
  Alert,
  Box,
  Button,
  Container,
  IconButton,
  InputAdornment,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Paper,
  TextField,
  Typography,
} from "@mui/material";
import { ToggleButton, ToggleButtonGroup } from "@mui/material";
import { describeError } from "./api/client";
import {
  connectAlpaca,
  fetchOnboardingStatus,
  restartOnboarding,
  retryOnboardingStep,
  type OnboardingStatus,
  type OnboardingStep,
  type StepCode,
} from "./api/onboarding";
import {
  PROFILE_LABELS,
  PROFILE_ORDER,
  fetchUserProfile,
  updateUserProfile,
  type ExperienceProfile,
} from "./api/userProfile";

// Onboarding Alpaca — comportement inchangé depuis B07, habillage Material
// UI ajouté en B25 (§commentaire d'origine : "MUI arrive en bloc en B25,
// décision confirmée par Zac après le retour sur B06"). Bloque toujours
// l'accès au contexte Paper tant qu'aucun compte n'est connecté (§B07
// "Bloquer le dashboard Paper sans compte valide") — voir l'intégration
// dans App.tsx, également inchangée.

const STEP_LABELS: Record<StepCode, string> = {
  credentials_validated: "Identifiants validés",
  paper_environment_confirmed: "Environnement Paper confirmé",
  account_synchronized: "Compte synchronisé",
  portfolio_loaded: "Portefeuille chargé",
  assets_synchronized: "Actifs synchronisés",
  market_stream_established: "Flux de marché établi",
  mcp_session_initialized: "Session MCP initialisée",
  ai_agents_ready: "Agents IA prêts",
};

const STATUS_ICON: Record<OnboardingStep["status"], React.ReactNode> = {
  PENDING: <RadioButtonUncheckedIcon fontSize="small" color="disabled" />,
  RUNNING: <SyncIcon fontSize="small" color="primary" />,
  COMPLETED: <CheckCircleIcon fontSize="small" color="success" />,
  FAILED: <ErrorIcon fontSize="small" color="error" />,
};

// §B30 "Choix du profil pendant l'onboarding" — appel indépendant à
// `PUT /api/settings/profile`, zéro couplage avec la machine à états
// `_STUBBED_STEPS`/`_run_real_step` de l'onboarding (voir docstring
// `backend/app/routers/user_profile.py`) : ce sélecteur peut échouer,
// rester ignoré, ou être modifié plus tard dans Settings sans jamais
// affecter la progression des 8 étapes de connexion Alpaca ci-dessous. Pas
// de dialog de confirmation ici (contrairement à `ProfileCard.tsx` en
// Settings) : à ce stade il n'y a pas encore de niveau d'autonomie établi à
// "augmenter", seulement un premier choix.
const PROFILE_DESCRIPTIONS: Record<ExperienceProfile, string> = {
  novice: "1 stratégie active, 2 symboles, approbation obligatoire avant chaque ordre.",
  intermediate: "2 stratégies actives, 5 symboles, approbation optionnelle.",
  expert: "3 stratégies actives, 10 symboles, approbation configurable.",
};

type Props = {
  onConnected: (status: OnboardingStatus) => void;
};

export default function Onboarding({ onConnected }: Props) {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [revealSecret, setRevealSecret] = useState(false);
  const [phase, setPhase] = useState<"idle" | "loading" | "connecting" | "retrying" | "restarting">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);
  const [detailsOpenFor, setDetailsOpenFor] = useState<StepCode | null>(null);
  const [profile, setProfile] = useState<ExperienceProfile | null>(null);
  const [profileSaving, setProfileSaving] = useState(false);

  useEffect(() => {
    // Chargement initial uniquement — `onConnected` est `setOnboarding`
    // (identité stable, State setter React), l'inclure ne provoque pas de
    // re-déclenchement inattendu de cet effet.
    fetchOnboardingStatus()
      .then((result) => {
        setStatus(result);
        if (result.account?.status === "connected") onConnected(result);
      })
      .catch(() => setError("Impossible de contacter le serveur."))
      .finally(() => setPhase("idle"));
    fetchUserProfile()
      .then((result) => setProfile(result.profile))
      .catch(() => {
        // §non-bloquant — un profil non chargé n'empêche pas de connecter
        // le compte Alpaca ; le sélecteur reste simplement absent et le
        // profil par défaut (`novice`, posé côté backend) s'applique.
      });
  }, [onConnected]);

  async function handleProfileSelect(next: ExperienceProfile | null) {
    if (!next || next === profile || profileSaving) return;
    const previous = profile;
    setProfile(next);
    setProfileSaving(true);
    try {
      await updateUserProfile(next);
    } catch {
      setProfile(previous);
    } finally {
      setProfileSaving(false);
    }
  }

  async function handleConnect(event: React.FormEvent) {
    event.preventDefault();
    setPhase("connecting");
    setError(null);
    try {
      const result = await connectAlpaca(apiKey, secretKey);
      setStatus(result);
      if (result.account?.status === "connected") onConnected(result);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setPhase("idle");
    }
  }

  async function handleRetry() {
    setPhase("retrying");
    setError(null);
    try {
      const result = await retryOnboardingStep();
      setStatus(result);
      if (result.account?.status === "connected") onConnected(result);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setPhase("idle");
    }
  }

  async function handleRestart() {
    setPhase("restarting");
    setError(null);
    try {
      const result = await restartOnboarding();
      setStatus(result);
      setApiKey("");
      setSecretKey("");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setPhase("idle");
    }
  }

  if (phase === "loading") {
    return (
      <Container maxWidth="sm" sx={{ py: 8 }}>
        <Typography>Chargement…</Typography>
      </Container>
    );
  }

  // Un compte existe dès la première tentative (même invalide) et survit à
  // "Restart complete setup" (§B07 reset_pipeline ne supprime pas la ligne
  // compte, il la remet à "pending" avec toutes les étapes PENDING — voir
  // backend/app/onboarding.py). `account !== null` seul ne suffit donc pas à
  // détecter "une tentative est en cours ou terminée" : après un restart,
  // aucune étape n'a encore tourné, il faut redonner le formulaire à
  // l'utilisateur plutôt que d'afficher une liste de 8 étapes PENDING sans
  // aucun moyen de ressaisir des clés (bug détecté lors de la vérification
  // manuelle navigateur — le "Restart" bloquait silencieusement l'écran).
  const hasStarted =
    status?.account !== null &&
    status?.account !== undefined &&
    status.steps.some((s) => s.status !== "PENDING");
  const failedStep = status?.steps.find((s) => s.status === "FAILED") ?? null;

  return (
    <Container maxWidth="sm" sx={{ py: 6 }}>
      <Typography variant="h4" component="h1" sx={{ mb: 1 }}>
        Connecter ton compte Alpaca Paper
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Fonds simulés uniquement — aucune carte bancaire requise, aucun argent réel ne sera jamais
        engagé. Tes clés sont chiffrées avant d'être enregistrées et ne sont jamais renvoyées en
        clair.
      </Typography>

      {!hasStarted && profile && (
        <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
            Ton profil d'expérience
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 2 }}>
            Modifiable à tout moment dans Settings. Détermine les limites par défaut de tes stratégies — les risques et
            pertes potentiels restent toujours affichés, quel que soit le profil.
          </Typography>
          <ToggleButtonGroup
            value={profile}
            exclusive
            onChange={(_e, next) => handleProfileSelect(next)}
            disabled={profileSaving}
            sx={{ mb: 1, flexWrap: "wrap" }}
          >
            {PROFILE_ORDER.map((p) => (
              <ToggleButton key={p} value={p}>
                {PROFILE_LABELS[p]}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          <Typography variant="body2" color="text.secondary">
            {PROFILE_DESCRIPTIONS[profile]}
          </Typography>
        </Paper>
      )}

      {!hasStarted && (
        <Paper variant="outlined" sx={{ p: 4 }}>
          <Box component="form" onSubmit={handleConnect} noValidate>
            <TextField
              id="apiKey"
              label="API Key"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              fullWidth
              margin="normal"
              autoComplete="off"
            />
            <TextField
              id="secretKey"
              label="Secret Key"
              type={revealSecret ? "text" : "password"}
              value={secretKey}
              onChange={(e) => setSecretKey(e.target.value)}
              fullWidth
              margin="normal"
              autoComplete="off"
              slotProps={{
                input: {
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton onClick={() => setRevealSecret((v) => !v)} edge="end" size="small">
                        {revealSecret ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                      </IconButton>
                    </InputAdornment>
                  ),
                },
              }}
            />
            {error && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {error}
              </Alert>
            )}
            <Button
              type="submit"
              variant="contained"
              disabled={phase === "connecting" || !apiKey || !secretKey}
              sx={{ mt: 3 }}
            >
              {phase === "connecting" ? "Vérification…" : "Connect & Verify"}
            </Button>
          </Box>
        </Paper>
      )}

      {hasStarted && status && (
        <Box sx={{ mt: 3 }}>
          <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
            Progression
          </Typography>
          <List dense>
            {status.steps.map((step) => (
              <Box key={step.step_code}>
                <ListItem disableGutters>
                  <ListItemIcon sx={{ minWidth: 32 }}>{STATUS_ICON[step.status]}</ListItemIcon>
                  <ListItemText
                    primary={STEP_LABELS[step.step_code]}
                    secondary={
                      step.status === "FAILED" && step.error_details?.message ? (
                        <>
                          <Typography component="span" variant="body2" color="error">
                            {step.error_details.message}
                          </Typography>{" "}
                          <Button
                            size="small"
                            onClick={() =>
                              setDetailsOpenFor(detailsOpenFor === step.step_code ? null : step.step_code)
                            }
                          >
                            View technical details
                          </Button>
                        </>
                      ) : step.status === "COMPLETED" && step.error_details?.note ? (
                        // §B07 audit du 28/08 — jusqu'ici cette note (posée
                        // honnêtement côté backend, voir `_STUBBED_STEPS`
                        // dans `backend/app/onboarding.py`) n'était jamais
                        // affichée : une étape stub apparaissait comme une
                        // vraie coche verte, indiscernable d'une étape
                        // réellement vérifiée. Zac (et un jury) doit pouvoir
                        // voir laquelle des 8 étapes est réellement prouvée.
                        <Typography component="span" variant="body2" color="text.secondary">
                          {step.error_details.note}
                        </Typography>
                      ) : undefined
                    }
                  />
                </ListItem>
                {detailsOpenFor === step.step_code && (
                  <Box
                    component="pre"
                    sx={{
                      bgcolor: "action.hover",
                      p: 1,
                      fontSize: "0.8rem",
                      overflowX: "auto",
                      borderRadius: 1,
                    }}
                  >
                    {JSON.stringify(step.error_details, null, 2)}
                  </Box>
                )}
              </Box>
            ))}
          </List>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          <Box sx={{ display: "flex", gap: 1 }}>
            {failedStep && (
              <Button variant="contained" onClick={handleRetry} disabled={phase === "retrying"}>
                {phase === "retrying" ? "Nouvelle tentative…" : "Retry this step"}
              </Button>
            )}
            <Button variant="outlined" color="inherit" onClick={handleRestart} disabled={phase === "restarting"}>
              {phase === "restarting" ? "Réinitialisation…" : "Restart complete setup"}
            </Button>
          </Box>

          {status.account?.balance && (
            <Box sx={{ mt: 3 }}>
              <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
                Solde du compte
              </Typography>
              <List dense disablePadding>
                <ListItem disableGutters>
                  <ListItemText
                    primary="Cash"
                    secondary={status.account.balance.cash.toLocaleString("fr-FR", {
                      style: "currency",
                      currency: "USD",
                    })}
                  />
                </ListItem>
                <ListItem disableGutters>
                  <ListItemText
                    primary="Valeur du portefeuille"
                    secondary={status.account.balance.portfolio_value.toLocaleString("fr-FR", {
                      style: "currency",
                      currency: "USD",
                    })}
                  />
                </ListItem>
                <ListItem disableGutters>
                  <ListItemText
                    primary="Pouvoir d'achat"
                    secondary={status.account.balance.buying_power.toLocaleString("fr-FR", {
                      style: "currency",
                      currency: "USD",
                    })}
                  />
                </ListItem>
              </List>
            </Box>
          )}
        </Box>
      )}
    </Container>
  );
}
