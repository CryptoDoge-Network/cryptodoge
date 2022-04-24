import React from 'react';
import { ModeProvider } from '@cryptodoge/core';
import AppRouter from './AppRouter';

export default function App() {
  return (
    <ModeProvider persist>
      <AppRouter />
    </ModeProvider>
  );
}
