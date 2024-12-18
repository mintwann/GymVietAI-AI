import joblib
import pandas as pd
import os
from flask import Flask, request, jsonify
from recommendation import NutritionPlanner, DietaryRestriction, Allergen, NutritionPlanFormatter

app = Flask(__name__)

# --- Configuration ---
MODELS_DIR = "./models"
# ERROR_CODES = {
#     1001: "Invalid input data",
#     1002: "Model not found",
#     500: "An unexpected error occurred",
# }

# --- Load models ---
def load_workout_models():
    try:
        models = {
            "asia": joblib.load(os.path.join(MODELS_DIR, "./exercise/random_forest_classifier_asian.pkl")),
            "europe": joblib.load(os.path.join(MODELS_DIR, "./exercise/random_forest_classifier_european.pkl")),
        }
        default_model = models["asia"]
    except FileNotFoundError as e:
        print(f"Error loading model: {e}")
        exit(1)
    return models, default_model

def load_nutrition_model():
    try:
        return joblib.load(os.path.join(MODELS_DIR, "./nutrition/random_forest_regressor.pkl"))
    except FileNotFoundError as e:
        print(f"Error loading nutrition model: {e}")
        exit(1)

wo_models, wo_default_model = load_workout_models()
nutrition_model = load_nutrition_model()

# --- Helper functions ---
def validate_input(data, required_fields, data_types):
    errors = []
    for field in required_fields:
        value = data.get(field)
        if value in [None, "", "null"]:
            errors.append(f"Missing required field: {field}")
        elif field == "Gender":
            try:
                data[field] = str(value).strip().capitalize()
                if data[field] not in ["Male", "Female"]:
                    errors.append(f"Invalid value for {field}: Gender must be 'Male' or 'Female'")
            except (ValueError, TypeError):
                errors.append(f"Invalid data type for {field}: Expected {data_types[field].__name__}")
        elif field == "Goal":
            try:
                data[field] = str(value)
                if data[field] not in ["Loss Weight", "Stay Fit", "Muscle Gain"]:
                    errors.append(f"Invalid value for {field}: Goal must be 'Loss Weight', 'Stay Fit', or 'Muscle Gain'")
            except (ValueError, TypeError):
                errors.append(f"Invalid data type for {field}: Expected {data_types[field].__name__}")
        elif field == "ActivityLevel":
            try:
                data[field] = str(value).strip().title()
                valid_activity_levels = ["Sedentary", "Lightly Active", "Moderately Active", "Active", "Very Active"]
                if data[field] not in valid_activity_levels:
                    errors.append(f"Invalid value for {field}: ActivityLevel must be one of {', '.join(valid_activity_levels)}")
            except (ValueError, TypeError):
                errors.append(f"Invalid data type for {field}: Expected a string")
        else:
            try:
                if field in ["Weight", "Height", "Age"]:
                    data[field] = float(value) if field != "Age" else int(value)
                else:
                    data[field] = str(value).strip()
            except (ValueError, TypeError):
                errors.append(f"Invalid data type for {field}: Expected {data_types[field].__name__}")
                
    # Validate numeric fields          
    for field in ["Weight", "Height", "Age"]:
        value = data.get(field)
        if isinstance(value, (int, float)) and value <= 0:
            errors.append(f"{field} must be a positive number")
        elif field in "Weight" and value > 300:
            errors.append(f"{field} must be less than 300")
        elif field == "Height" and value > 2.5:
            errors.append(f"{field} must be less than or equal to 2.5 meters")
        elif field == "Age" and value > 120:
            errors.append(f"{field} must be less than 120")           
    return errors

# --- API routes ---
@app.route('/', methods=['GET'])
def index():
    return """Welcome to the GymVietAI API!
    Use the /api/workout-plan endpoint with a POST request.
    Send a JSON object with the user's data to get a workout plan prediction.
    e.g. {'Gender': 'Male/Female', 'Weight': 70, 'Height': 1.70, 'Age': 25}
    
    Use the /api/nutrition-plan endpoint with a POST request.
    Send a JSON object with the user's data to get a nutrition plan prediction.
    e.g. {'Weight': 70, 'Height': 1.70, 'Age': 25, 'Gender': 'Male/Female', 'Goal': 'Loss Weight/Stay Fit/Muscle Gain', 'ActivityLevel': 'Sedentary/Lightly Active/Moderately Active/Active/Very Active'}
    Output will be a list of macronutrient targets [calories, protein, carbs, fat].
    """

@app.route('/api/workout-plan', methods=['POST'])
def predict():
    data = request.get_json()
    required_fields = ["Gender", "Weight", "Height", "Age", "continent"]
    data_types = {
        "Gender": str,
        "Weight": float,
        "Height": float,
        "Age": int,
        "continent": str,
    }

    # Validate input
    errors = validate_input(data, required_fields, data_types)
    if errors:
        return jsonify({"EC": 1001, "EM": ", ".join(errors), "DT": []}), 400

    # Predict
    try:
        continent = data["continent"].lower()
        model = wo_models.get(continent, wo_default_model)
        input_df = pd.DataFrame([data])
        prediction = int(model.predict(input_df)[0])
        return jsonify({"EC": 0, "EM": "", "DT": [prediction]}), 200
    except KeyError:
        return jsonify({"EC": 1002, "EM": f"Model not found for continent: {data.get('continent')}", "DT": []}), 404
    except Exception as e:
        return jsonify({"EC": 500, "EM": f"An unexpected error occurred: {str(e)}", "DT": []}), 500

@app.route('/api/nutrition-plan', methods=['POST'])
def predict_nutrition():
    data = request.get_json()
    required_fields = ["Weight", "Height", "Age", "Gender", "Goal", "ActivityLevel", "restrictions", "allergens"]
    data_types = {
        "Weight": float,
        "Height": float,
        "Age": int,
        "Gender": str,
        "Goal": str,
        "ActivityLevel": str,
        "restrictions": list,
        "allergens": list
    }
    
    # Get optional dietary preferences from request
    dietary_restrictions = set(map(DietaryRestriction, data.get('restrictions', ['none'])))
    allergens = set(map(Allergen, data.get('allergens', ['none'])))
    
    # Validate input
    errors = validate_input(data, required_fields, data_types)
    if errors:
        return jsonify({"EC": 1001, "EM": ", ".join(errors), "DT": []}), 400
    
    # Predict
    try:
        input_df = pd.DataFrame([data])
        macro_predictions = nutrition_model.predict(input_df)[0]
        
        # Format macro targets for the planner
        macro_targets = {
            'calories': float(macro_predictions[0]),
            'protein': float(macro_predictions[1]),
            'carbs': float(macro_predictions[2]),
            'fat': float(macro_predictions[3])
        }
        
        food_df = pd.read_csv('./data/food_dataset_new.csv')
        
        # Create nutrition planner instance
        planner = NutritionPlanner(
            food_data=food_df,
            macro_targets=macro_targets,
            dietary_restrictions=dietary_restrictions,
            allergens=allergens
        )
        
        # Generate weekly plan
        weekly_plan = planner.generate_weekly_plan()
        weekly_nutrition = planner.calculate_weekly_nutrition(weekly_plan)
        
        # Format the plan
        formatter = NutritionPlanFormatter(planner)
        formatted_plan = formatter.format_weekly_plan(weekly_plan, weekly_nutrition)
        
        response_data = {
            "macro_targets": macro_targets,
            "weekly_plan": formatted_plan
        }
        
        return jsonify({
            "EC": 0,
            "EM": "",
            "DT": response_data
        }), 200
        
    except Exception as e:
        return jsonify({
            "EC": 500, 
            "EM": f"An unexpected error occurred: {str(e)}", 
            "DT": []
        }), 500
    
    

if __name__ == '__main__':
    app.run(debug=True, port=5001)
