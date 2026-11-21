import { useLayoutEffect, useState } from 'react';
import { Capacitor, SystemBars, SystemBarsStyle } from '@capacitor/core';

export type Appearance = 'classic' | 'light' | 'dark';
const key = 'modus.appearance';
function savedAppearance(): Appearance {
  try {
    const saved = localStorage.getItem(key);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch { /* Practice can still open if preference storage is unavailable. */ }
  return 'classic';
}

export function useAppearance() {
  const [appearance, setAppearance] = useState<Appearance>(savedAppearance);
  const [storageMessage, setStorageMessage] = useState('');
  useLayoutEffect(() => {
    document.documentElement.dataset.appearance = appearance;
    const color = appearance === 'light' ? '#ffffff' : appearance === 'dark' ? '#080808' : '#10161e';
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', color);
    if (Capacitor.isNativePlatform()) {
      void SystemBars.setStyle({style:appearance === 'light' ? SystemBarsStyle.Light : SystemBarsStyle.Dark})
        .catch(() => { /* The page theme also works without native status bar support. */ });
    }
  }, [appearance]);
  function chooseAppearance(value: Appearance) {
    setAppearance(value);
    try {
      localStorage.setItem(key,value);
      setStorageMessage('');
    } catch { setStorageMessage('Appearance applied for this visit. This device could not save the preference.'); }
  }
  return {appearance, chooseAppearance, storageMessage};
}
