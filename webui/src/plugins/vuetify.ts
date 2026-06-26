// Vuetify instance + theme. All component colours reference these theme
// tokens — never hex/rgb literals in components (module-vue-vuetify:
// vuetify-theming).

import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'

import { createVuetify } from 'vuetify'

export default createVuetify({
  theme: {
    defaultTheme: 'instructionsLight',
    themes: {
      instructionsLight: {
        dark: false,
        colors: {
          primary: '#3B5BA5',
          secondary: '#5C6B73',
          surface: '#FFFFFF',
          background: '#F5F6F8',
          error: '#B3261E',
          info: '#2D6CDF',
          success: '#2E7D32',
          warning: '#ED6C02',
        },
      },
      instructionsDark: {
        dark: true,
        colors: {
          primary: '#9DB2E6',
          secondary: '#9AA8B0',
          surface: '#1E1F22',
          background: '#141517',
          error: '#F2B8B5',
          info: '#9EC1FF',
          success: '#7BD389',
          warning: '#FFB870',
        },
      },
    },
  },
})
