// Circuit Bench — desktop half. Plain ESM, loaded uncompiled by Hermes Desktop.
// Only @hermes/plugin-sdk, react and react/jsx-runtime are importable. Optional SDK parts: `sdk.X` + typeof check.
import * as sdk from '@hermes/plugin-sdk'
import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { jsx, jsxs, Fragment } from 'react/jsx-runtime'

const PLUGIN_ID = 'circuit-bench'
