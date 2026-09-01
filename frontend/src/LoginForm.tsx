import { useEffect, useState } from "react";
import { Alert, Box, Button, Container, Paper, TextField, Typography } from "@mui/material";
import { describeError } from "./api/client";
import { fetchDemoCredentials, login, type User } from "./api/auth";

// Écran de connexion — comportement inchangé depuis B05 (formulaire
// préchargé avec les identifiants démo), habillage Material UI ajouté en
// B25 (§commentaire d'origine : "le vrai habillage visuel arrive en B25").

type Props = {
  onLoggedIn: (user: User) => void;
};

export default function LoginForm({ onLoggedIn }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [demoHint, setDemoHint] = useState<{ email: string; password: string } | null>(null);

  useEffect(() => {
    fetchDemoCredentials()
      .then((creds) => {
        if (creds) {
          setDemoHint(creds);
          setEmail(creds.email);
          setPassword(creds.password);
        }
      })
      .catch(() => {
        // Pas grave si ça échoue — le formulaire reste utilisable vide.
      });
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const user = await login(email, password);
      onLoggedIn(user);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Container maxWidth="xs" sx={{ py: 8 }}>
      <Typography variant="h4" component="h1" align="center" sx={{ mb: 3 }}>
        ZikosoftTrader AI
      </Typography>
      <Paper variant="outlined" sx={{ p: 4 }}>
        <Box component="form" onSubmit={handleSubmit} noValidate>
          <TextField
            id="email"
            label="Email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            fullWidth
            margin="normal"
            autoComplete="username"
          />
          <TextField
            id="password"
            label="Mot de passe"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            fullWidth
            margin="normal"
            autoComplete="current-password"
          />
          {demoHint && (
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
              Identifiants de démo préremplis ({demoHint.email}) — modifiable si besoin.
            </Typography>
          )}
          {error && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {error}
            </Alert>
          )}
          <Button type="submit" variant="contained" fullWidth disabled={submitting} sx={{ mt: 3 }}>
            {submitting ? "Connexion…" : "Se connecter"}
          </Button>
        </Box>
      </Paper>
    </Container>
  );
}
