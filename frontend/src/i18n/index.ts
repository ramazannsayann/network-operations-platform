import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './locales/en.json'
import tr from './locales/tr.json'

/** UI languages; Turkish is the default. Code, identifiers and comments stay English. */
export const LANGUAGES = ['tr', 'en'] as const
export type Language = (typeof LANGUAGES)[number]

const STORAGE_KEY = 'netops.language'

function storedLanguage(): Language {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return LANGUAGES.find((language) => language === value) ?? 'tr'
  } catch {
    return 'tr'
  }
}

void i18n.use(initReactI18next).init({
  resources: { tr: { translation: tr }, en: { translation: en } },
  lng: storedLanguage(),
  fallbackLng: 'tr',
  interpolation: { escapeValue: false }, // React escapes
})

document.documentElement.lang = i18n.language
i18n.on('languageChanged', (language) => {
  document.documentElement.lang = language
  try {
    localStorage.setItem(STORAGE_KEY, language)
  } catch {
    // private mode: the choice lasts for this page only
  }
})

export default i18n
