import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-[#050810]">
          <div className="bg-gray-900/80 border border-red-500/30 rounded-xl p-8 max-w-md w-full backdrop-blur-xl">
            <h2 className="text-lg font-semibold text-red-400 mb-2">Something went wrong</h2>
            <p className="text-sm text-gray-400 mb-4">{this.state.error?.message}</p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="px-4 py-2 bg-teal-600 hover:bg-teal-500 text-white text-sm rounded-lg"
            >
              Try again
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
