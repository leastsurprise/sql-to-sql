#!/usr/bin/python
# encoding: UTF-8
from __future__ import unicode_literals
import re, sys, getopt, json, os, base64
from typing import ByteString

tag_text = ''
chain_detachment_character = 'ቖ'  # \u1256
base_dir = ''

# When parsing we have the problem that opening quotes and closing quotes are not
# marked up as "opening" or "closing" within the text, but we want to modify our
# behaviour to suit this state.  So here we surface that state to make later processing
# easier.

def deal_with_quotes(text):
    retVal = ''
    awaiting_closing_bracket = False
    prev_char = ''
    single_open = False
    double_open = False
    for x in re.finditer('.', text, flags=re.DOTALL):
        x = x.group()
       
        if x == "'" and awaiting_closing_bracket:
            x = 'ↈ' # u2188 means single quote (within brackets [])
        if x == '"' and awaiting_closing_bracket:
            x = 'ↇ'  # u2187 means double quote (within brackets [])

        if x in ('"', "'") and not (awaiting_closing_bracket or prev_char == r'\\'):
            if x == '"':
                if single_open:
                    x = 'ಣ' # mask double quotes contained within single quotes with \u0CA3
                else:
                    if double_open:
                        x = "®"  # close double quote
                    else:
                        x = "©"  # open double quote
                    double_open = not double_open

            if x == "'":
                if double_open:
                    x = 'ଲ' # mask single quotes contained within double quotes with \u0CA3
                else:
                    if single_open:
                        x = "«"  # close single quote
                    else:
                        x = "»"  # open single quote
                    single_open = not single_open

        if x == '[' and not prev_char == r'\\':
            awaiting_closing_bracket = True
        elif x == ']' and not prev_char == r'\\':
            awaiting_closing_bracket = False

        if x == r'\(' and (single_open or double_open):
            x = 'ൕ'
        elif x  == r'\)' and (single_open or double_open):
            x = 'ಒ'

        if x == ',':
            if single_open or double_open:
                x = '⋒'   # u22D2 means comma (within a string)
            elif awaiting_closing_bracket:
                x = '∷' # u2237 means comma (within brackets [])
       
        retVal += x
        prev_char = x
    return retVal


def deal_with_interrim_code(txt):
    retVal = txt
    # During the migration process we might discover that there are code blocks we want to
    # insert into the output, and naturally these code blocks will be native to the destination
    # language, meaning they might not run on the source language.
    # Meanwhile, we are still developing in the source language because the world does not stand
    # still, and we need to run alterative code.  The solution is to comment these rival source and
    # destination language blocks in or out as necessary.
    # Maintain your source and destination blocks in the Source code base.
    # Comment out the destination code block, leaving the source code block live.

    # This is an example:

#        /* IF_MIGRATING_THEN_START
#        select regexp_encode(x.owner_name) as owner_name
#             , regexp_encode(x.orig_owner_name) as orig_owner_name
#             , regexp_encode(x.masked_name) as masked_name
#           IF_MIGRATING_THEN_FINISH */
#        /* IF_NOT_MIGRATING_THEN_START */
#        select x.owner_name
#             , x.orig_owner_name
#             , x.masked_name
#        /* IF_NOT_MIGRATING_THEN_FINISH */

    # This code uncomments the destination source block by closing off the
    # IF_MIGRATING_THEN_START comment / tag and prefixing "IF_MIGRATING_THEN_FINISH */" with a comment start.
    retVal = re.sub(r'\/\*\s+IF_MIGRATING_THEN_START', '/* IF_MIGRATING_THEN_START */', retVal)
    retVal = re.sub(r'IF_MIGRATING_THEN_FINISH\s+\*\/', '/* IF_MIGRATING_THEN_FINISH */', retVal)
    # This code removes any source code blocks specific to the source system
    retVal = re.sub(r'\/\*\s+IF_NOT_MIGRATING_THEN_START\s+.*?IF_NOT_MIGRATING_THEN_FINISH\s+\*\/', '', retVal, flags=re.IGNORECASE|re.DOTALL)

    # So the output becomes:
#        /* IF_MIGRATING_THEN_START */
#        select regexp_encode(x.owner_name) as owner_name
#             , regexp_encode(x.orig_owner_name) as orig_owner_name
#             , regexp_encode(x.masked_name) as masked_name
#        /* IF_MIGRATING_THEN_FINISH */
#        /* IF_NOT_MIGRATING_THEN_START
#        select x.owner_name
#             , x.orig_owner_name
#             , x.masked_name
#           IF_NOT_MIGRATING_THEN_FINISH */

    # WARNING do not allow /* */ style comments in your source or destination interrim code blocks
    # because that will cause problems.

    return retVal


def mask_sql_text(txt):
    retVal = txt
    for x in re.finditer(r"\/\*.*?\*\/", retVal, flags=re.IGNORECASE|re.DOTALL):
        retVal = retVal[:x.start()] + re.sub(r"'|\"",' ',retVal[x.start():x.end()]) + retVal[x.end():]
    for x in re.finditer(r"--.*?\n", retVal, flags=re.IGNORECASE):
        retVal = retVal[:x.start()] + re.sub(r"'|\"",' ',retVal[x.start():x.end()]) + retVal[x.end():]
    retVal = deal_with_quotes(retVal)
    return retVal


def unmask_sql_text(txt):
    global only_allowable_string_quote_character
    global adhoc_regexp
    single_quote_unmask_character = "'"
    double_quote_unmask_character = '"'
    if len(only_allowable_string_quote_character) > 0:
        single_quote_unmask_character = only_allowable_string_quote_character
        double_quote_unmask_character = only_allowable_string_quote_character
    retVal = txt
    retVal = re.sub(chain_detachment_character, '', retVal)
    retVal = re.sub(r"ಣ", '"', retVal)  # unmask double quotes contained within single quotes with \u0CA3
    retVal = re.sub(r"ଲ",  "'", retVal)  # unmask single quotes contained within double quotes with \u0CA3
    retVal = re.sub(r"©|®", double_quote_unmask_character, retVal) # unmask double quotes
    retVal = re.sub(r"»|«", single_quote_unmask_character, retVal) # unmask single quotes
    retVal = re.sub(r"∷", ",", retVal)   # unmask comma within brackets []
    retVal = re.sub("ↈ", "'", retVal)    # unmask single quote within brackets []
    retVal = re.sub("ↇ", '"', retVal)    # unmask double quote within brackets []
    retVal = re.sub(r"ൕ", "(", retVal)  # unmask opening parentheses
    retVal = re.sub(r"ಒ", ")", retVal)   # unmask closing parentheses
    retVal = re.sub(r"⋒", ",", retVal)   # unmask comma within a string
    retVal = re.sub(r"⊙", ' ', retVal)   # dissolve the temp-token-glue
    for pairing in adhoc_regexp:
        search_string = pairing["SEARCH_STR"]
        replacement_string = pairing["REPLACEMENT_STR"]
        retVal = re.sub(search_string, replacement_string, retVal, flags=re.IGNORECASE)
    return retVal


# Having the end user (who modifies migration_map.json) build PARSER_REGEXP
# directly is asking for keying errors, and requires knowledge of regexp
# that is not widespread.  So it is worth the code to do it here.
def build_function_parser_regexp(func_keyword, func_map):
    # Negative lookahead is used here so that if we have nested function
    # arg1 maps to "arg" as expected, and not to "func(func(func(func(arg"
    match_str = r'\b' + func_keyword + r"\((?!" + func_keyword + r")"
    return match_str


# the end user needs to maintain a control file "migration_map.json"
# The top level keys are the names of impala functions.
# These need two keys - args_in and translation.
# A third key, 'PARSER_REGEXP' is built from the top level name.
def migrate_as_per_json(txt):
    global base_dir
    global adhoc_regexp

    block_to_skip_because_hand_migrated = identify_sections_markedup_for_hand_migration(txt)
    with open(os.path.join(base_dir,"migration_map.json")) as f:
        func_map = json.load(f)
    for key in func_map.keys():
        if key != 'ADHOC_REGEXP':
            func_map[key]['PARSER_REGEXP'] = build_function_parser_regexp(key, func_map[key])
    for next_func in func_map:
        if next_func == 'ADHOC_REGEXP':
            adhoc_regexp = func_map[next_func]
            continue
        # for loop is used to unwind nested functions
        source_function_regexp = func_map[next_func]['PARSER_REGEXP']
        # We are going to be changing the string we are iterating over
        # So the danger is that the indexes we precompute will no longer align with the
        # insert points.
        # BUT if we work from the end of the string back to the front this will not be
        # an issue, hence the reversed().  B2f == back to front
        b2f = []
        for x in re.finditer(source_function_regexp, txt, flags=re.IGNORECASE):
            b2f.append(x)
        for x in reversed(b2f):
            # txt = re.sub(source_function_regexp, sink_function_regexp, txt, count=1, flags=re.IGNORECASE)
            # Note how we are only applying the re.sub operation to a tiny part of the whole string,
            # the part that is currently matched.  Otherwise we get problems when the replacement also matches
            # the search string.
            harvested_args = []
            parentheses_count = 0
            current_arg = ''
            chars_parsed = 0
            distinct_applied = False
            str_start = x.start() + len(next_func) + 1
            if match_is_in_section_markedup_for_hand_migration(block_to_skip_because_hand_migrated, x):
                continue
            str_finish = str_start + 2000
            for y in re.finditer(r'.', txt[str_start:str_finish], flags=re.IGNORECASE|re.DOTALL):
                chars_parsed += 1
                y = y.group()
                # An argument might be a function which itself contains functions as arguments
                # so we use parentheses counting to detect the end of these arguments.
                parentheses_count += y.count('(')
                parentheses_count -= y.count(')')
                if (y == ',' and parentheses_count == 0) or (parentheses_count == -1):
                    harvested_args.append(current_arg.strip())
                    current_arg = ''
                    if parentheses_count == -1:
                        break
                else:
                    current_arg += y
                    if len(harvested_args) == 0 and distinct_applied == False and current_arg.upper().strip() == 'DISTINCT':
                        distinct_applied = True
                        current_arg = ''

            output_function_args = ''
            suppress_comma = False
            for sfarg in func_map[next_func]["ARGUMENTS_AND_LITERALS_MAP"]:
                if sfarg == '_SUPPRESS_COMMA_':
                    suppress_comma = True
                    continue
                if len(output_function_args) > 0 and not suppress_comma:
                    output_function_args += ','
                suppress_comma = False
                if not isinstance(sfarg, int):
                    # This is a literal argument such as 'month'
                    output_function_args += sfarg
                else:
                    idx = sfarg - 1
                    if idx < len(harvested_args):
                        output_function_args += harvested_args[idx]

            (output_function_pre, output_function_post) = func_map[next_func]["DESTINATION_LANGUAGE_FUNCTION_TEMPLATE"].split('_ARGS_')
            if distinct_applied: output_function_pre += 'DISTINCT '
            str_finish = str_start + chars_parsed
            this_tag = ''
            if len(tag_text) > 0:
                this_tag = ' /* ' + re.sub('_+', '_', tag_text + '_' + next_func).strip() + ' */ '
            txt = txt[:x.start()] + chain_detachment_character + output_function_pre + output_function_args + output_function_post + this_tag + txt[str_finish:]
               
    txt = re.sub(',,',',',txt)         # now tidy up double commas (argument separators) e.g; somefunc(arg1,,arg2) to somefunc(arg1,arg2)
    txt = re.sub(r'(?<=\(),+','',txt)  # correct somefunc(,somearg) to somefunc(somearg)
    txt = re.sub(r',+(?=\))','',txt)   # correct somefunc(somearg,) to somefunc(somearg)
    return txt


def identify_sections_markedup_for_hand_migration(txt):
    retVal = []
    for x in re.finditer(r'\/\* IF_MIGRATING_THEN_START.*?IF_MIGRATING_THEN_FINISH \*\/', txt, flags=re.DOTALL|re.IGNORECASE):
        retVal.append( {'start': x.start(), 'end': x.end() })
    return retVal


def match_is_in_section_markedup_for_hand_migration(skips, m):
    for n in skips:
        if m.start() > n['start'] and m.start() < n['end']:
            return True
    return False


#def print_command_line_options():
#    print('evolve.py -h                  [Show help (this)]')
#    print('evolve.py -i <inputpath> -o <outputpath> -t <tag text> -q <only allowable string quote character>')
#    print('                              [migrate the source language functions in <inputpath> to destination language functions, writing result to <outputpath>.]')
#    print('                              [The optional <tag text> is appended to migrations, along with the source function name, to enable checking of the migration.]')
#    print('                              [The optional <only allowable string quote character> is useful when your destination language only allows one style of]')
#    print('                              [quote (single or double) to book end strings. This actually happens in the wild.]')
#    print('NOTE: <inputpath> and <outputpath> must both be a file or both be a directory.')
#    print('      if <inputpath> is a directory then all .sas and .sql files there are read, processed, and output to <outputpath>.')
#    print('Setup and maintainance:')
#    print('      The -l option requires a file listing the source language functions, named "source_language_function_list.txt".')
#    print('      You must maintain a file named migration_map.json that describes how source language functions are to be migrated. The file contains a dictionary')
#    print('      structure, with the top level keys being the names of source language functions (uppercased) to be migrated.  The value for these keys is also a')
#    print('      dictionary with two entries: DESTINATION_LANGUAGE_FUNCTION_TEMPLATE and ARGUMENTS_AND_LITERALS_MAP."')
#    print('      The value for DESTINATION_LANGUAGE_FUNCTION_TEMPLATE must be a string, containing the text "_ARGS_".  You may be tempted to place literal values')
#    print('      here, but they are better placed in the value of the ARGUMENTS_AND_LITERALS_MAP key. In some instances your source function may be best migrated')
#    print('      to a nesting of destination functions, in which case the value of the DESTINATION_LANGUAGE_FUNCTION_TEMPLATE key would be something like this:')
#    print('      "DESTFUNC1(DESTFUNCT2(DESTFUNC3(_ARGS_)))". Where there is a one to one mapping between the source function and the destination function, the')
#    print('      value would look like this: "DESTFUNC(_ARGS_)".')
#    print('      The value for the ARGUMENTS_AND_LITERALS_MAP key is an array which can hold strings (these act as literals or fixed arguments) or integers.    ')
#    print('      Integer values are indexes into the arguments passed to the source function.                                                                   ')
#    print('      Given this source code -')
#    print('           source_func1(17,a_function_returning_a_float(function_returns_who_knows_what(3,44), 62),"b")')
#    print('      we get these arguments that we can index -')
#    print('      1: 17')
#    print('      2: a_function_returning_a_float(function_returns_who_knows_what(3,44), 62)')
#    print('      3: "b"')
#    print('      As far as evolve.py is concerned, these are all strings, and it does not care if they are valid arguments for the source function.')
#    print('      When mapping these functions to the destination source, we might need to change their order or insert literals, and we might not be')
#    print('      able to use all of the arguments available in the source language. We define this in the value to the ARGUMENTS_AND_LITERALS_MAP key, like so:')
#    print('      "ARGUMENTS_AND_LITERALS_MAP": [3, "MY_LITERAL", 1]')
#    print('      Note how the order of arguments has been changed, a literal inserted, and one argument has not been used.')
#       
#    return


if __name__ == '__main__':
    no_option_given = True
    inputpath = ''
    outputpath = ''
    file_queue = []
    source_language_function_list_re = []
    only_allowable_string_quote_character = ''
    adhoc_regexp = []

    try:
        opts, args = getopt.getopt(sys.argv[1:],"hli:o:t:q:")
    except getopt.GetoptError:
        sys.exit(2)
    for opt, arg in opts:
        no_option_given = False
        if opt == '-i':
            inputpath = os.path.join(base_dir,arg)
        elif opt == '-o':
            outputpath = os.path.join(base_dir,arg)
        elif opt == '-t':
            tag_text = arg
        elif opt == 'q':
            only_allowable_string_quote_character = arg.strip()
    if no_option_given:
        sys.exit(0)
    if inputpath != '':
        try:
            if os.path.isdir(inputpath) and os.path.isdir(outputpath):
                for input_file in [f for f in os.listdir(inputpath) if os.path.isfile(os.path.join(inputpath, f)) and re.match('.*(sas|sql)$', f, flags=re.IGNORECASE)]:
                    file_queue.append({
                        "input_file": os.path.join(inputpath, input_file)
                      , "output_file": os.path.join(outputpath, input_file)  # we are doing a full migration so need an output file
                    })
            elif os.path.isfile(inputpath) and not os.path.isdir(outputpath):
                file_queue.append({
                    "input_file": inputpath
                })
            else:
                sys.exit(0)
        except IOError:
            print("Could not read " + inputpath)
            sys.exit(2)

    for f in file_queue:    
        endpoint_text = ''
        try:
            source_text = (open(f["input_file"], "rt", encoding='utf-8')).read()
        except IOError:
            print("Could not open/read " + f["output_file"])
            sys.exit(2)
        masked_text = mask_sql_text(deal_with_interrim_code(source_text))
        # Now, we need to deal with chaining.
        # the regexes that detect a function to migrate (rightly) only find the inner function of
        # a chain of functions.  Which means we need multiple passes to replace all of a chain.
        # I limit to 30, incase of runaway re-writing.
        # I also deal with the possibility that the rewritten (migrated) function has the same name
        # (just different arguments) by masking the name, which bypasses the innermost-member-of-the-chain only
        # protection.  Then at the end, I remove all the masking.
        last_masked_text = masked_text
        for i in range(1,30):
            masked_text = migrate_as_per_json(masked_text)
            if last_masked_text == masked_text:
                endpoint_text = unmask_sql_text(masked_text)
                print("Migrated " + f["input_file"] + " in " + str(i - 1) + " cycles.")
                break
            else:
                last_masked_text = masked_text
        
        try:
            o = open(f["output_file"], 'wt', encoding='utf-8')
            o.write(endpoint_text)
        except IOError:
            print("Could not write " + f["output_file"])
            sys.exit(2)