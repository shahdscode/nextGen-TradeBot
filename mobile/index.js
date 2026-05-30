import 'react-native-gesture-handler'
import { enableScreens } from 'react-native-screens'
import { registerRootComponent } from 'expo'
import App from './rootApp'

enableScreens()

registerRootComponent(App)
