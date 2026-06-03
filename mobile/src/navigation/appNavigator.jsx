import { View, ActivityIndicator, StyleSheet } from 'react-native'
import { NavigationContainer } from '@react-navigation/native'
import { createNativeStackNavigator } from '@react-navigation/native-stack'
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'
import { Ionicons } from '@expo/vector-icons'

import { useAuth } from '../context/authContext'
import { COLORS } from '../constants/theme'

import LoginScreen     from '../screens/loginScreen'
import HomeScreen      from '../screens/homeScreen'
import SignalsScreen   from '../screens/signalsScreen'
import MarketScreen    from '../screens/marketScreen'
import LeaderboardScreen from '../screens/leaderboardScreen'
import PortfolioScreen from '../screens/portfolioScreen'
import ProfileScreen from '../screens/profileScreen'

const Stack = createNativeStackNavigator()
const Tab   = createBottomTabNavigator()

const tabIcons = {
  Home: 'home-outline',
  Portfolio: 'wallet-outline',
  Signals: 'pulse-outline',
  Market: 'bar-chart-outline',
  Leaderboard: 'trophy-outline',
  Profile: 'person-outline',
}

function TabIcon({ label, focused }) {
  const name = tabIcons[label] || 'ellipse-outline'
  return (
    <Ionicons
      name={name}
      size={24}
      color={focused ? COLORS.teal : COLORS.tabInactive}
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
      <Tab.Screen name="Portfolio" component={PortfolioScreen} />
      <Tab.Screen name="Signals" component={SignalsScreen} />
      <Tab.Screen name="Market" component={MarketScreen} />
      <Tab.Screen name="Leaderboard" component={LeaderboardScreen} />
      <Tab.Screen name="Profile" component={ProfileScreen} />
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
})
