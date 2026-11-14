import { createContext, useContext } from 'react'
import type { DeckData } from './lib/load'

export const DeckContext = createContext<DeckData | null>(null)

export function useDeck(): DeckData | null {
  return useContext(DeckContext)
}
