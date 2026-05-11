try:
    from xgboost import XGBRegressor
except Exception:
    XGBRegressor = None

class GBMEdgeModel:
    def __init__(self, features, target):
        self.features = features
        self.target = target
        self.model = None

        if XGBRegressor is not None:
            self.model = XGBRegressor(
                n_estimators=500,
                max_depth=5,
                learning_rate=0.03,
                subsample=0.9,
                colsample_bytree=0.9,
                objective="reg:squarederror"
            )

    def train(self, df):
        if self.model is None:
            return False
        X = df[self.features]
        y = df[self.target]
        self.model.fit(X, y)
        return True

    def predict(self, row):
        if self.model is None:
            return None
        return self.model.predict(row[self.features])[0]
