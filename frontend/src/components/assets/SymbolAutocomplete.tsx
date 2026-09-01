// §B09 — remplace le champ libre "Symboles (séparés par des virgules)" de
// `StrategiesPage.tsx` par une sélection contre le catalogue réellement
// synchronisé (`GET /api/assets/search`), avec filtrage des actifs non
// négociables (§checklist "Filtrer les actifs non tradables") plutôt que de
// laisser l'utilisateur taper un symbole qui échouera plus tard au passage
// d'ordre. Debounce maison (300ms) — même principe que `useLivePolling`
// (D058) : pas de dépendance supplémentaire pour un besoin aussi ciblé.

import { useEffect, useState } from "react";
import { Autocomplete, Chip, CircularProgress, TextField } from "@mui/material";
import { searchAssets, type AssetSearchItem } from "../../api/assets";

const DEBOUNCE_MS = 300;

// Un symbole déjà sélectionné (venant de `value`, une simple liste de
// chaînes — l'interface publique du composant) peut ne plus figurer dans
// les résultats de recherche courants (l'utilisateur a retapé autre chose
// entre-temps) : on reconstruit un item minimal plutôt que de perdre
// l'affichage de son chip.
function _placeholderItem(symbol: string): AssetSearchItem {
  return {
    canonical_symbol: symbol,
    label: symbol,
    asset_type: "equity",
    tradable: true,
    fractionable: false,
    shortable: false,
  };
}

export default function SymbolAutocomplete({
  value,
  onChange,
  maxSymbols,
}: {
  value: string[];
  onChange: (symbols: string[]) => void;
  maxSymbols?: number;
}) {
  const [inputValue, setInputValue] = useState("");
  const [options, setOptions] = useState<AssetSearchItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const handle = setTimeout(() => {
      setLoading(true);
      searchAssets(inputValue, { limit: 15, tradableOnly: true })
        .then((res) => {
          if (!cancelled) setOptions(res.items);
        })
        .catch(() => {
          if (!cancelled) setOptions([]);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [inputValue]);

  const atLimit = maxSymbols !== undefined && value.length >= maxSymbols;
  // §checklist "Filtrer les actifs non tradables" : contrairement à
  // l'ancien champ libre, aucun symbole ne peut être ajouté sans venir du
  // catalogue synchronisé (pas de `freeSolo`) — et plus aucune suggestion
  // n'est proposée une fois le plafond du profil atteint (§B30), même si
  // la suppression via les chips reste toujours possible.
  const effectiveOptions = atLimit ? [] : options;

  return (
    <Autocomplete
      multiple
      options={effectiveOptions}
      getOptionLabel={(o) => o.canonical_symbol}
      isOptionEqualToValue={(o, v) => o.canonical_symbol === v.canonical_symbol}
      filterOptions={(opts) => opts}
      inputValue={inputValue}
      //onInputChange={(_e, newInput) => setInputValue(newInput)}
      onInputChange={(_event, newInputValue, reason) => {
        if (reason === "input") {
          setInputValue(newInputValue);
        }

        if (reason === "clear") {
          setInputValue("");
        }
      }}
      value={value.map((symbol) => options.find((o) => o.canonical_symbol === symbol) ?? _placeholderItem(symbol))}
      onChange={(_event, selected) => {
        const symbols = selected.map((item) => item.canonical_symbol);

        onChange(
          Array.from(new Set(symbols)).slice(0, maxSymbols)
        );

        setInputValue("");
      }}
      /*onChange={(_e, selected) => {
        const symbols = selected.map((s) => s.canonical_symbol);
        onChange(Array.from(new Set(symbols)).slice(0, maxSymbols));
      }}*/
      loading={loading}
      renderOption={(props, option) => (
        <li {...props} key={option.canonical_symbol}>
          {option.canonical_symbol} — {option.label}
        </li>
      )}
      renderValue={(itemsValue, getItemProps) =>
        itemsValue.map((option, index) => {
          const { key, ...itemProps } = getItemProps({ index });
          return <Chip key={key} label={option.canonical_symbol} size="small" {...itemProps} />;
        })
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label="Symboles"
          placeholder={atLimit ? `Maximum ${maxSymbols} atteint` : "Rechercher un symbole…"}
          helperText={
            maxSymbols !== undefined
              ? `${value.length}/${maxSymbols} symbole(s) — au moins un requis`
              : "Au moins un symbole requis"
          }
          slotProps={{
            ...params.slotProps,
            input: {
              ...params.slotProps.input,
              endAdornment: (
                <>
                  {loading ? <CircularProgress color="inherit" size={16} /> : null}
                  {params.slotProps.input.endAdornment}
                </>
              ),
            },
          }}
        />
      )}
    />
  );
}
