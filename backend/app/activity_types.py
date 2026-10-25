"""Turn provider sport types into the categories shown on My training.

Strava sends `sport_type` (e.g. VirtualRide, EMountainBikeRide); Garmin sends
`typeKey` (e.g. virtual_ride, e_bike_mountain). Both map to one short list so
the activity mix, filters and the AI coach speak the same language. An
athlete's own override wins.
"""

CATEGORIES = {
    # Strava sport_type
    "Ride": "Road",
    "VirtualRide": "Virtual",
    "MountainBikeRide": "MTB",
    "EMountainBikeRide": "E-MTB",
    "EBikeRide": "E-Bike",
    "GravelRide": "Gravel",
    "Velomobile": "Road",
    "Handcycle": "Road",
    "Run": "Run",
    "TrailRun": "Trail run",
    "VirtualRun": "Treadmill run",
    "Walk": "Walk",
    "Hike": "Hike",
    "Swim": "Swim",
    "WeightTraining": "Strength",
    "Crossfit": "Strength",
    "Workout": "Workout",
    "HighIntensityIntervalTraining": "Workout",
    "Yoga": "Yoga",
    "Pilates": "Yoga",
    "RockClimbing": "Climbing",
    "Rowing": "Rowing",
    "VirtualRow": "Rowing",
    "NordicSki": "Ski",
    "AlpineSki": "Ski",
    "BackcountrySki": "Ski",
    # Garmin typeKey
    "road_biking": "Road",
    "cycling": "Road",
    "virtual_ride": "Virtual",
    "indoor_cycling": "Virtual",
    "mountain_biking": "MTB",
    "e_bike_mountain": "E-MTB",
    "e_bike_fitness": "E-Bike",
    "gravel_cycling": "Gravel",
    "running": "Run",
    "trail_running": "Trail run",
    "treadmill_running": "Treadmill run",
    "indoor_running": "Treadmill run",
    "walking": "Walk",
    "hiking": "Hike",
    "lap_swimming": "Swim",
    "open_water_swimming": "Swim",
    "strength_training": "Strength",
    "hiit": "Workout",
    "cardio": "Workout",
    "yoga": "Yoga",
    "pilates": "Yoga",
    "indoor_rowing": "Rowing",
    "rowing": "Rowing",
}

# What an athlete can pick as a type override, in display order.
CHOICES = sorted(set(CATEGORIES.values()) | {"Other"}, key=lambda c: (c == "Other", c))

RIDES = {"Road", "Virtual", "MTB", "E-MTB", "E-Bike", "Gravel"}
INDOOR = {"Virtual", "Treadmill run"}


def category(activity) -> str:
    if activity.type_override:
        return activity.type_override
    base = CATEGORIES.get(activity.sport, "Other")
    # A ride on a smart trainer recorded as a normal ride is still indoor.
    if base == "Road" and activity.indoor:
        return "Virtual"
    return base


def is_ride(activity) -> bool:
    return category(activity) in RIDES


def is_outdoor(activity) -> bool:
    return not activity.indoor and category(activity) not in INDOOR
