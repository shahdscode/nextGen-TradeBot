import { View, ActivityIndicator, StyleSheet } from 'react-native'
import { NavigationContainer } from '@react-navigation/native'
import { createNativeStackNavigator } from '@react-navigation/native-stack'
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'
import { Ionicons } from '@expo/vector-icons'

import { useAuth } from '../context/authContext'
import { COLORS } from '../constants/theme'
import BrandHeader from '../components/brandHeader'

import SplashScreen from '../screens/splashScreen'
import WelcomeScreen from '../screens/welcomeScreen'
import SignInScreen from '../screens/signInScreen'
import SignUpScreen from '../screens/signUpScreen'
import HomeScreen from '../screens/homeScreen'
import SignalsScreen from '../screens/signalsScreen'
import MarketScreen from '../screens/marketScreen'
import LeaderboardScreen from '../screens/leaderboardScreen'
import PortfolioScreen from '../screens/portfolioScreen'
import ProfileScreen from '../screens/profileScreen'
import TradeJournalScreen from '../screens/tradeJournalScreen'
import TradeDetailScreen from '../screens/tradeDetailScreen'

const Stack = createNativeStackNavigator()
const Tab = createBottomTabNavigator()
const AuthStack = createNativeStackNavigator()

const tabIcons = {
  Home: 'home-outline',
  Portfolio: 'wallet-outline',
  Signals: 'pulse-outline',
  Market: 'bar-chart-outline',
  Leaderboard: 'trophy-outline',
  Profile: 'person-outline',
}

function TabIcon({ label, focused, color }) {
  const name = tabIcons[label] || 'ellipse-outline'
  const active = color || COLORS.teal
  return (
    <Ionicons
      name={name}
      size={24}
      color={focused ? active : COLORS.tabInactive}
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
        tabBarActiveTintColor: route.name === 'Profile' ? COLORS.purple : COLORS.teal,
        tabBarInactiveTintColor: COLORS.tabInactive,
        tabBarIcon: ({ focused }) => (
          <TabIcon
            label={route.name}
            focused={focused}
            color={route.name === 'Profile' && focused ? COLORS.purple : undefined}
          />
        ),
      })}
    >
      <Tab.Screen name="Home" component={HomeScreen} />
      <Tab.Screen name="Market" component={MarketScreen} />
      <Tab.Screen name="Signals" component={SignalsScreen} />
      <Tab.Screen name="Portfolio" component={PortfolioScreen} />
      <Tab.Screen name="Leaderboard" component={LeaderboardScreen} />
      <Tab.Screen name="Profile" component={ProfileScreen} />
    </Tab.Navigator>
  )
}

function AuthFlow() {
  return (
    <AuthStack.Navigator
      screenOptions={{ headerShown: false, animation: 'fade' }}
      initialRouteName="Splash"
    >
      <AuthStack.Screen name="Splash" component={SplashScreen} />
      <AuthStack.Screen name="Welcome" component={WelcomeScreen} />
      <AuthStack.Screen name="SignIn" component={SignInScreen} />
      <AuthStack.Screen name="SignUp" component={SignUpScreen} />
    </AuthStack.Navigator>
  )
}

function BootLoading() {
  return (
    <View style={styles.loading}>
      <BrandHeader size="large" subtitle="Loading…" />
      <ActivityIndicator color={COLORS.teal} size="large" style={styles.spinner} />
    </View>
  )
}

export default function AppNavigator() {
  const { user, loading } = useAuth()

  if (loading) return <BootLoading />

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {user ? (
          <>
            <Stack.Screen name="Main" component={MainTabs} />
            <Stack.Screen name="TradeJournal" component={TradeJournalScreen}
              options={{ headerShown: true, title: 'Trade Journal',
                headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: COLORS.textPrimary,
                headerShadowVisible: false }} />
            <Stack.Screen name="TradeDetail" component={TradeDetailScreen}
              options={{ headerShown: true, title: 'Decision',
                headerStyle: { backgroundColor: COLORS.bg }, headerTintColor: COLORS.textPrimary,
                headerShadowVisible: false }} />
          </>
        ) : (
          <Stack.Screen
            name="Auth"
            component={AuthFlow}
            options={{ animation: 'fade' }}
          />
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
    paddingHorizontal: 32,
  },
  spinner: { marginTop: 32 },
})
