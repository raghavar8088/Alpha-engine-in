package strategy

// AllStrategies returns the full S1-S50 strategy roster.
func AllStrategies() []Strategy {
	return []Strategy{
		// S1–S9: foundation strategies
		NewORBBreakout(),
		NewVWAPReversion(),
		NewIVCrushThetaDecay(),
		NewPCRExtremeReversal(),
		NewMaxPainMagnet(),
		NewOIBuildupDirectional(),
		NewGapFillOpening(),
		NewEMARibbonTrendRider(),
		NewEventVolatilityFade(),
		// S10–S16: scalping (1m–5m)
		NewTickScalpBidAskCompression(),
		NewPullbackScalpVWAPMicro(),
		NewVolumeSpikeScalpOrderFlow(),
		NewEMARibbonScalpFast(),
		NewBreakoutScalpSupportResistance(),
		NewRSIDivergenceScalp(),
		NewATRBreakoutScalpVolatility(),
		// S17–S22: intraday (15m–1h)
		NewOpeningRangeBreakoutIntraday(),
		NewVWAPMeanReversionStraddle(),
		NewADXTrendFilterBreakouts(),
		NewFibonacciRetracementIntraday(),
		NewBollingerBandSqueezeBreakoutIntraday(),
		NewNewsEventVolFadeOptionsSell(),
		// S23–S29: swing (daily–weekly)
		NewWeeklyOptionsThetaDecayStrangle(),
		NewMomentumBreakoutSwing(),
		NewMeanReversionRSIOversoldSwing(),
		NewSectorRotationNiftyRebalance(),
		NewGapFadeOptions(),
		NewEarningsStraddleIVPlay(),
		NewIndexFuturesPositionalTrend(),
		// S30–S36: advanced scalping
		NewSuperTrendScalper(),
		NewVWAPBandBounce(),
		NewOpening15minORBFutures(),
		NewTickVelocityScalp(),
		NewDeltaWeightedOptionsScalp(),
		NewEMA921ZeroLagScalp(),
		NewATRChannelBreakoutScalp(),
		// S37–S43: advanced intraday
		NewOpeningGapStrategy(),
		NewVWAPMultiTouchBreakout(),
		NewIntradayFibonacciRetracement(),
		NewStochasticRSIDivergence(),
		NewTimeOfDayMomentum(),
		NewIntradayOIReversal(),
		NewCPRPivotBreakout(),
		// S44–S47: advanced swing
		NewWeeklyOptionsMomentum(),
		NewPositionalBreakoutSwing(),
		NewMeanReversionSwing(),
		NewEarningsEventStrangle(),
		// S48–S50: index options
		NewBankNiftyOptionsStraddle(),
		NewNiftyIronCondor(),
		NewNiftyATMCalendarSpread(),
	}
}

// FoundationStrategies returns the 4 lowest-options-chain-complexity
// strategies, per the build order in Part 12 of the spec: validate the
// pipeline on these before activating the options-chain-heavy ones.
func FoundationStrategies() []Strategy {
	return []Strategy{
		NewORBBreakout(),
		NewVWAPReversion(),
		NewPCRExtremeReversal(),
		NewEMARibbonTrendRider(),
	}
}

// ScalpingStrategies returns S10–S16.
func ScalpingStrategies() []Strategy {
	return []Strategy{
		NewTickScalpBidAskCompression(),
		NewPullbackScalpVWAPMicro(),
		NewVolumeSpikeScalpOrderFlow(),
		NewEMARibbonScalpFast(),
		NewBreakoutScalpSupportResistance(),
		NewRSIDivergenceScalp(),
		NewATRBreakoutScalpVolatility(),
	}
}

// IntradayStrategies returns S17–S22.
func IntradayStrategies() []Strategy {
	return []Strategy{
		NewOpeningRangeBreakoutIntraday(),
		NewVWAPMeanReversionStraddle(),
		NewADXTrendFilterBreakouts(),
		NewFibonacciRetracementIntraday(),
		NewBollingerBandSqueezeBreakoutIntraday(),
		NewNewsEventVolFadeOptionsSell(),
	}
}

// SwingStrategies returns S23–S29.
func SwingStrategies() []Strategy {
	return []Strategy{
		NewWeeklyOptionsThetaDecayStrangle(),
		NewMomentumBreakoutSwing(),
		NewMeanReversionRSIOversoldSwing(),
		NewSectorRotationNiftyRebalance(),
		NewGapFadeOptions(),
		NewEarningsStraddleIVPlay(),
		NewIndexFuturesPositionalTrend(),
	}
}

// AdvancedScalpingStrategies returns S30–S36.
func AdvancedScalpingStrategies() []Strategy {
	return []Strategy{
		NewSuperTrendScalper(),
		NewVWAPBandBounce(),
		NewOpening15minORBFutures(),
		NewTickVelocityScalp(),
		NewDeltaWeightedOptionsScalp(),
		NewEMA921ZeroLagScalp(),
		NewATRChannelBreakoutScalp(),
	}
}

// AdvancedIntradayStrategies returns S37–S43.
func AdvancedIntradayStrategies() []Strategy {
	return []Strategy{
		NewOpeningGapStrategy(),
		NewVWAPMultiTouchBreakout(),
		NewIntradayFibonacciRetracement(),
		NewStochasticRSIDivergence(),
		NewTimeOfDayMomentum(),
		NewIntradayOIReversal(),
		NewCPRPivotBreakout(),
	}
}

// AdvancedSwingStrategies returns S44–S47.
func AdvancedSwingStrategies() []Strategy {
	return []Strategy{
		NewWeeklyOptionsMomentum(),
		NewPositionalBreakoutSwing(),
		NewMeanReversionSwing(),
		NewEarningsEventStrangle(),
	}
}

// IndexOptionsStrategies returns S48–S50.
func IndexOptionsStrategies() []Strategy {
	return []Strategy{
		NewBankNiftyOptionsStraddle(),
		NewNiftyIronCondor(),
		NewNiftyATMCalendarSpread(),
	}
}
