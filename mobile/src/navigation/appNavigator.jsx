import { View, Image, ActivityIndicator, StyleSheet } from 'react-native'
import { NavigationContainer } from '@react-navigation/native'
import { createNativeStackNavigator } from '@react-navigation/native-stack'
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'

import { useAuth } from '../context/authContext'
import { COLORS } from '../constants/theme'

import LoginScreen     from '../screens/loginScreen'
import HomeScreen      from '../screens/homeScreen'
import SignalsScreen   from '../screens/signalsScreen'
import MarketScreen    from '../screens/marketScreen'
import LeaderboardScreen from '../screens/leaderboardScreen'
import SimulatorScreen from '../screens/simulatorScreen'

const Stack = createNativeStackNavigator()
const Tab   = createBottomTabNavigator()

const tabIcons = {
  Home: require('../../assets/tabs/home.png'),
  Signals: require('../../assets/tabs/signals.png'),
  Market: require('../../assets/tabs/market.png'),
  Leaderboard: require('../../assets/tabs/leaderboard.png'),
  Simulator: require('../../assets/tabs/simulator.png'),
}

function TabIcon({ label, focused }) {
  const source = tabIcons[label]
  if (!source) return null
  return (
    <Image
      source={source}
      style={[styles.tabIcon, { opacity: focused ? 1 : 0.5 }]}
      resizeMode="contain"
    />
  )
}

function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: {
          backgroundColor: COLORS.bg,
          borderTopColor: COLORS.cardBorder,
          borderTopWidth: 1,
          paddingBottom: 8,
          paddingTop: 6,
          height: 60,
        },
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: '600',
          marginTop: 2,
        },
        tabBarActiveTintColor: COLORS.teal,
        tabBarInactiveTintColor: COLORS.tabInactive,
        tabBarIcon: ({ focused }) => <TabIcon label={route.name} focused={focused} />,
      })}
    >
      <Tab.Screen name="Home" component={HomeScreen} />
      <Tab.Screen name="Signals" component={SignalsScreen} />
      <Tab.Screen name="Market" component={MarketScreen} />
      <Tab.Screen name="Leaderboard" component={LeaderboardScreen} />
      <Tab.Screen name="Simulator" component={SimulatorScreen} />
    </Tab.Navigator>
  )
}

function LoadingScreen() {
  return (
    <View style={styles.loading}>
      <ActivityIndicator color={COLORS.teal} size="large" />
    </View>
  )
}

export default function AppNavigator() {
  const { user, loading } = useAuth()

  if (loading) return <LoadingScreen />

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {user ? (
          <Stack.Screen name="Main" component={MainTabs} />
        ) : (
          <Stack.Screen name="Login" component={LoginScreen} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  )
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    backgroundColor: COLORS.bg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabIcon: {
    width: 28,
    height: 28,
  },
})
