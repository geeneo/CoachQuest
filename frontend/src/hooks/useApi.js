import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api.js";

// Tiny fetch hook: { data, loading, error, reload }. Pass null to skip.
export function useApi(path) {
  const [state, setState] = useState({ data: null, loading: !!path, error: null });

  const load = useCallback(async () => {
    if (!path) return;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      setState({ data: await api(path), loading: false, error: null });
    } catch (error) {
      setState({ data: null, loading: false, error });
    }
  }, [path]);

  useEffect(() => {
    load();
  }, [load]);

  return { ...state, reload: load };
}
