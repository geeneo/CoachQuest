import { createContext, useContext } from "react";

// True on an athlete's pages when the viewer only looks (a friend, or an admin without a share):
// components hide their editing controls. The API refuses changes either way.
export const ReadOnly = createContext(false);

export function useReadOnly() {
  return useContext(ReadOnly);
}
