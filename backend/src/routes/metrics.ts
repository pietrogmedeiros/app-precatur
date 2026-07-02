import { Router } from "express";
import { getSummary, getByOwner, getFunnel, getTimeseries } from "../queries";

export const metricsRouter = Router();

metricsRouter.get("/summary", async (_req, res, next) => {
  try {
    res.json(await getSummary());
  } catch (err) {
    next(err);
  }
});

metricsRouter.get("/by-owner", async (_req, res, next) => {
  try {
    res.json(await getByOwner());
  } catch (err) {
    next(err);
  }
});

metricsRouter.get("/funnel", async (_req, res, next) => {
  try {
    res.json(await getFunnel());
  } catch (err) {
    next(err);
  }
});

metricsRouter.get("/timeseries", async (_req, res, next) => {
  try {
    res.json(await getTimeseries());
  } catch (err) {
    next(err);
  }
});
