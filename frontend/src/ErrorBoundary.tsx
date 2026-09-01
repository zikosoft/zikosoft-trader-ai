import { Component, type ErrorInfo, type ReactNode } from "react";
import { Alert, AlertTitle, Box, Button, Container, Typography } from "@mui/material";

// §B25 "Error boundaries" — filet de sécurité générique : une exception de
// rendu dans UNE page (ex. une future page B26/B27/B28 mal branchée) ne doit
// jamais faire disparaître tout le shell (menu, header, bandeau d'incident)
// derrière un écran blanc. `error.tsx`/`ErrorInfo` restent uniquement dans
// `console.error` — jamais envoyés nulle part (aucun service de collecte
// d'erreurs frontend n'existe dans ce projet ; le journal d'erreurs
// applicatif B36 couvre le backend, pas le rendu React).

type Props = { children: ReactNode };
type State = { error: Error | null };

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary a intercepté une exception de rendu :", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <Container maxWidth="sm" sx={{ py: 8 }}>
          <Alert severity="error">
            <AlertTitle>Une erreur inattendue est survenue</AlertTitle>
            <Typography variant="body2" sx={{ mb: 2 }}>
              Cette partie de l'application a rencontré un problème. Le reste de ZikosoftTrader AI
              (dont le bandeau d'incident système) reste fonctionnel.
            </Typography>
            <Box>
              <Button variant="outlined" color="inherit" onClick={() => window.location.reload()}>
                Recharger la page
              </Button>
            </Box>
          </Alert>
        </Container>
      );
    }
    return this.props.children;
  }
}
