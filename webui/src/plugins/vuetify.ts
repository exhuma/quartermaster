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
    },
  },
})
