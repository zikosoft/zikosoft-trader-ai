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
  PROFILE_ORDER,
  fetchUserProfile,
  updateUserProfile,
  type ExperienceProfile,
} from "./api/userProfile";
import { formatCurrency } from "./i18n/formatters";
import { useI18n } from "./i18n/I18nContext";
import { profileLabel } from "./i18n/domain";

// Onboarding Alpaca — comportement inchangé depuis B07, habillage Material
// UI ajouté en B25 (§commentaire d'origine : "MUI arrive en bloc en B25,
// décision confirmée par Zac après le retour sur B06"). Bloque toujours
// l'accès au contexte Paper tant qu'aucun compte n'est connecté (§B07
// "Bloquer le dashboard Paper sans compte valide") — voir l'intégration
// dans App.tsx, également inchangée.

const STEP_LABEL_KEYS: Record<StepCode, string> = {
  credentials_validated: "onboarding.step.credentialsValidated",
  paper_environment_confirmed: "onboarding.step.paperEnvironmentConfirmed",
  account_synchronized: "onboarding.step.accountSynchronized",
  portfolio_loaded: "onboarding.step.portfolioLoaded",
  assets_synchronized: "onboarding.step.assetsSynchronized",
  market_stream_established: "onboarding.step.marketStreamEstablished",
  mcp_session_initialized: "onboarding.step.mcpSessionInitialized",
  ai_agents_ready: "onboarding.step.aiAgentsReady",
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
const PROFILE_DESCRIPTION_KEYS: Record<ExperienceProfile, string> = {
  novice: "onboarding.profile.novice",
  intermediate: "onboarding.profile.intermediate",
  expert: "onboarding.profile.expert",
};

type Props = {
  onConnected: (status: OnboardingStatus) => void;
};

export default function Onboarding({ onConnected }: Props) {
  const { locale, t } = useI18n();
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
      .catch((err) => setError(describeError(err)))
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
        <Typography>{t("common.loading")}</Typography>
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
        {t("onboarding.title")}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        {t("onboarding.introduction")}
      </Typography>

      {!hasStarted && profile && (
        <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
            {t("onboarding.profileTitle")}
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 2 }}>
            {t("onboarding.profileBody")}
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
                {profileLabel(t, p)}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          <Typography variant="body2" color="text.secondary">
            {t(PROFILE_DESCRIPTION_KEYS[profile])}
          </Typography>
        </Paper>
      )}

      {!hasStarted && (
        <Paper variant="outlined" sx={{ p: 4 }}>
          <Box component="form" onSubmit={handleConnect} noValidate>
            <TextField
              id="apiKey"
              label={t("onboarding.apiKey")}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              fullWidth
              margin="normal"
              autoComplete="off"
            />
            <TextField
              id="secretKey"
              label={t("onboarding.secretKey")}
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
                      <IconButton
                        onClick={() => setRevealSecret((v) => !v)}
                        edge="end"
                        size="small"
                        aria-label={revealSecret ? t("onboarding.hideSecret") : t("onboarding.showSecret")}
                      >
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
              {phase === "connecting" ? t("onboarding.verifying") : t("onboarding.connectAndVerify")}
            </Button>
          </Box>
        </Paper>
      )}

      {hasStarted && status && (
        <Box sx={{ mt: 3 }}>
          <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
            {t("onboarding.progress")}
          </Typography>
          <List dense>
            {status.steps.map((step) => (
              <Box key={step.step_code}>
                <ListItem disableGutters>
                  <ListItemIcon sx={{ minWidth: 32 }}>{STATUS_ICON[step.status]}</ListItemIcon>
                  <ListItemText
                    primary={t(STEP_LABEL_KEYS[step.step_code])}
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
                            {t("onboarding.viewTechnicalDetails")}
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
                {phase === "retrying" ? t("onboarding.retrying") : t("onboarding.retryStep")}
              </Button>
            )}
            <Button variant="outlined" color="inherit" onClick={handleRestart} disabled={phase === "restarting"}>
              {phase === "restarting" ? t("onboarding.restarting") : t("onboarding.restartSetup")}
            </Button>
          </Box>

          {status.account?.balance && (
            <Box sx={{ mt: 3 }}>
              <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
                {t("onboarding.accountBalance")}
              </Typography>
              <List dense disablePadding>
                <ListItem disableGutters>
                  <ListItemText
                    primary={t("onboarding.cash")}
                    secondary={formatCurrency(locale, status.account.balance.cash)}
                  />
                </ListItem>
                <ListItem disableGutters>
                  <ListItemText
                    primary={t("onboarding.portfolioValue")}
                    secondary={formatCurrency(locale, status.account.balance.portfolio_value)}
                  />
                </ListItem>
                <ListItem disableGutters>
                  <ListItemText
                    primary={t("onboarding.buyingPower")}
                    secondary={formatCurrency(locale, status.account.balance.buying_power)}
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
